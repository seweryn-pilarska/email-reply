import logging
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
from collections import defaultdict

from google.oauth2.credentials import Credentials
from dateutil import rrule
from dateutil import parser as date_parser # Alias to avoid confusion with our parser module if any

# Import find_events from the sibling module
try:
    # Use absolute imports for consistency
    import src.calendar_actions as calendar_actions  # Changed from .calendar_actions for compatibility
    from src.models import GoogleCalendarEvent        # Changed from .models for compatibility
except ImportError:
    # Handle potential path issues if run directly or structured differently
    logging.error("Could not import from src.calendar_actions or src.models. Ensure structure is correct.")
    # Define dummy functions/classes for type hinting if needed, or re-raise
    def find_events(*args, **kwargs): return None
    class GoogleCalendarEvent: pass


logger = logging.getLogger(__name__)

# Define a structure for projected occurrences (can be a TypedDict or Pydantic model later)
class ProjectedEventOccurrence:
    def __init__(self, original_event_id: str, original_summary: str, occurrence_start: datetime, occurrence_end: datetime):
        self.original_event_id = original_event_id
        self.original_summary = original_summary
        self.occurrence_start = occurrence_start
        self.occurrence_end = occurrence_end

    def __repr__(self):
        return f"ProjectedOccurrence(id='{self.original_event_id}', summary='{self.original_summary}', start='{self.occurrence_start}', end='{self.occurrence_end}')"


def project_recurring_events(
    credentials: Credentials,
    time_min: datetime,
    time_max: datetime,
    calendar_id: str = 'primary',
    event_query: Optional[str] = None
) -> List[ProjectedEventOccurrence]:
    """Finds recurring events and projects their occurrences within a time window.

    Args:
        credentials: Valid Google OAuth2 credentials.
        time_min: Start of the projection window (timezone-aware recommended).
        time_max: End of the projection window (timezone-aware recommended).
        calendar_id: The calendar to search within.
        event_query: Optional text query to filter master recurring events (e.g., "Birthday").

    Returns:
        A list of ProjectedEventOccurrence objects representing calculated occurrences.
    """
    projected_occurrences: List[ProjectedEventOccurrence] = []

    logger.info(f"Starting projection of recurring events for calendar '{calendar_id}'")
    logger.info(f"Projection window: {time_min} to {time_max}. Query: '{event_query or 'None'}'")

    # 1. Find master recurring events (not single instances)
    # We need events *within* the window OR whose recurrence *starts* before the window ends
    # and *might* generate instances within the window.
    # Finding events without timeMin/timeMax might be too broad.
    # A safe approach is to find master events potentially active *before* the window ends.
    master_events_response = calendar_actions.find_events(
        credentials=credentials,
        calendar_id=calendar_id,
        # timeMax=time_max, # Find masters that haven't ended before our window
        q=event_query,
        single_events=False, # Crucial: Get the master event definition
        showDeleted=False,
        max_results=2500 # Adjust as needed, API max is 2500
    )

    if not master_events_response or not master_events_response.items:
        logger.info("No master recurring events found matching the criteria.")
        return []

    logger.debug(f"Found {len(master_events_response.items)} potential master events.")

    # 2. Iterate through master events and parse recurrence rules
    for event in master_events_response.items:
        if not event.recurrence:
            # logger.debug(f"Skipping non-recurring event: {event.summary} ({event.id})")
            continue # Skip non-recurring events

        if not event.start or not (event.start.dateTime or event.start.date):
             logger.warning(f"Skipping recurring event without start time: {event.summary} ({event.id})")
             continue

        # Determine the start datetime of the recurrence series (dtstart)
        # Handle both date and dateTime cases
        dtstart_obj: Optional[datetime] = None
        event_duration: Optional[timedelta] = None

        if event.start.dateTime:
            try:
                # Use dateutil parser for robust ISO parsing
                dtstart_obj = date_parser.isoparse(event.start.dateTime)
                if event.end and event.end.dateTime:
                    dtend_obj = date_parser.isoparse(event.end.dateTime)
                    event_duration = dtend_obj - dtstart_obj
                else:
                    # Default duration for dateTime events if end is missing (e.g., 1 hour)
                    event_duration = timedelta(hours=1)
                    logger.warning(f"Recurring event '{event.summary}' missing end.dateTime, assuming {event_duration} duration.")
            except ValueError as e:
                 logger.error(f"Could not parse dateTime for event {event.summary} ({event.id}): {e}")
                 continue
        elif event.start.date:
            try:
                # All-day event - parse date and set time to midnight
                start_date = date_parser.parse(event.start.date).date()
                # Make dtstart timezone-aware if time_min is, otherwise naive UTC
                dtstart_obj = datetime.combine(start_date, datetime.min.time())
                if time_min.tzinfo:
                     # Try to use the target window's timezone, otherwise UTC fallback
                     dtstart_obj = dtstart_obj.replace(tzinfo=time_min.tzinfo)
                # else:
                     # dtstart_obj = dtstart_obj.replace(tzinfo=timezone.utc) # Requires import

                # Duration for all-day events is typically 1 day
                if event.end and event.end.date:
                    end_date = date_parser.parse(event.end.date).date()
                    event_duration = end_date - start_date # This includes the start day but excludes the end day
                else:
                    event_duration = timedelta(days=1) # Assume single all-day event
            except ValueError as e:
                 logger.error(f"Could not parse date for event {event.summary} ({event.id}): {e}")
                 continue

        if not dtstart_obj or event_duration is None:
             logger.error(f"Could not determine dtstart or duration for event {event.summary} ({event.id})")
             continue

        # Extract RRULE, EXDATE, RDATE strings
        # Google Calendar API returns recurrence as a list of strings
        # e.g., ['RRULE:FREQ=WEEKLY;UNTIL=20110701T170000Z', 'EXDATE:20110610T100000Z']
        rrule_str: Optional[str] = None
        exdate_strs: List[str] = []
        rdate_strs: List[str] = []
        for rule_str in event.recurrence:
            if rule_str.startswith('RRULE:'):
                rrule_str = rule_str # Assume only one RRULE per event
            elif rule_str.startswith('EXDATE'):
                exdate_strs.append(rule_str)
            elif rule_str.startswith('RDATE'):
                rdate_strs.append(rule_str)

        if not rrule_str:
            logger.warning(f"Recurring event '{event.summary}' ({event.id}) has no RRULE string. Skipping.")
            continue

        try:
            # Parse the main recurrence rule
            # Pass dtstart, which is essential for rrule calculations
            ruleset = rrule.rruleset()
            # Use rrulestr which handles RRULE and dtstart implicitly if not provided otherwise
            # We need to make sure the timezone handling matches dtstart_obj
            main_rule = rrule.rrulestr(rrule_str, dtstart=dtstart_obj, forceset=True) # forceset=True to handle COUNT/UNTIL easily
            ruleset.rrule(main_rule[0]) # Add the parsed rule to the set

            # Add exception dates (EXDATE)
            for exdate_str in exdate_strs:
                # EXDATE format: "EXDATE;TZID=Europe/Zurich:20110426T080000,20110428T080000"
                # Or "EXDATE:20240101" (all-day)
                # Or "EXDATE:20240101T100000Z" (UTC)
                # dateutil.rrule.rrulestr can parse EXDATE directly if part of the string,
                # but Google separates them. We need to parse dates/datetimes manually.
                # Split by ':' and then by ','
                parts = exdate_str.split(':', 1)
                if len(parts) == 2:
                    param_str, dates_str = parts
                    dates = dates_str.split(',')
                    params = {}
                    if ';' in param_str: # Check for TZID or VALUE=DATE
                       param_parts = param_str.split(';')[1:] # Skip EXDATE itself
                       for part in param_parts:
                           if '=' in part:
                               key, value = part.split('=', 1)
                               params[key.upper()] = value

                    is_all_day = params.get('VALUE') == 'DATE'
                    tz_id = params.get('TZID')
                    # TODO: Handle TZID properly using pytz if needed

                    for date_str in dates:
                        try:
                            if is_all_day:
                                ex_date = date_parser.parse(date_str).date()
                                # Create datetime at midnight for comparison/ruleset
                                ex_dt = datetime.combine(ex_date, datetime.min.time())
                                if dtstart_obj.tzinfo: # Match tzinfo
                                    ex_dt = ex_dt.replace(tzinfo=dtstart_obj.tzinfo)
                            else:
                                ex_dt = date_parser.isoparse(date_str)
                                # TODO: Apply TZID if present

                            ruleset.exdate(ex_dt)
                        except ValueError:
                            logger.warning(f"Could not parse EXDATE value '{date_str}' for event {event.id}")

            # Add explicit recurrence dates (RDATE) - Less common?
            # Similar parsing logic as EXDATE if needed.
            # for rdate_str in rdate_strs: ... ruleset.rdate(...)

            # Generate occurrences within the desired window [time_min, time_max)
            # Note: rruleset.between includes dates equal to dtstart/until
            occurrences = ruleset.between(time_min, time_max, inc=True) # inc=True includes time_min

            logger.debug(f"Event '{event.summary}' ({event.id}): Found {len(occurrences)} occurrences via rrule.")

            for occ_start_dt in occurrences:
                 # Ensure timezone consistency if needed
                 if dtstart_obj.tzinfo and occ_start_dt.tzinfo is None:
                      occ_start_dt = occ_start_dt.replace(tzinfo=dtstart_obj.tzinfo)
                 elif not dtstart_obj.tzinfo and occ_start_dt.tzinfo:
                      occ_start_dt = occ_start_dt.replace(tzinfo=None)

                 # Calculate occurrence end time
                 occ_end_dt = occ_start_dt + event_duration

                 # Double check if the occurrence actually overlaps the window
                 # ruleset.between should handle this, but an extra check might be useful
                 # if occ_start_dt < time_max and occ_end_dt > time_min:
                 projected_occurrences.append(
                      ProjectedEventOccurrence(
                           original_event_id=event.id,
                           original_summary=event.summary or "No Summary",
                           occurrence_start=occ_start_dt,
                           occurrence_end=occ_end_dt
                      )
                 )

        except Exception as e:
            logger.error(f"Failed to parse/process recurrence for event '{event.summary}' ({event.id}): {e}", exc_info=True)
            continue # Skip this event

    logger.info(f"Finished projection. Found {len(projected_occurrences)} total occurrences.")
    # Sort occurrences chronologically?
    projected_occurrences.sort(key=lambda x: x.occurrence_start)
    return projected_occurrences 


def analyze_busyness(
    credentials: Credentials,
    time_min: datetime,
    time_max: datetime,
    calendar_id: str = 'primary',
) -> Dict[date, Dict[str, Any]]:
    """Analyzes event count and total duration per day within a time window.

    Args:
        credentials: Valid Google OAuth2 credentials.
        time_min: Start of the analysis window (timezone-aware recommended).
        time_max: End of the analysis window (timezone-aware recommended).
        calendar_id: The calendar to analyze.

    Returns:
        A dictionary mapping each date within the window to its busyness stats:
        {'event_count': int, 'total_duration_minutes': float}
    """
    busyness_by_date: Dict[date, Dict[str, Any]] = defaultdict(lambda: {'event_count': 0, 'total_duration_minutes': 0.0})

    logger.info(f"Starting busyness analysis for calendar '{calendar_id}'")
    logger.info(f"Analysis window: {time_min} to {time_max}")

    # 1. Find all event instances in the range
    events_response = calendar_actions.find_events(
        credentials=credentials,
        calendar_id=calendar_id,
        time_min=time_min,
        time_max=time_max,
        single_events=True, # Get individual instances
        showDeleted=False,
        max_results=2500 # Consider pagination for very long ranges
    )

    if not events_response or not events_response.items:
        logger.info("No events found in the specified time range for busyness analysis.")
        return dict(busyness_by_date) # Return empty default dict converted to regular dict

    logger.debug(f"Found {len(events_response.items)} event instances for analysis.")

    # 2. Process events and aggregate stats by date
    for event in events_response.items:
        start_dt: Optional[datetime] = None
        end_dt: Optional[datetime] = None
        event_date: Optional[date] = None

        # Determine start and end datetimes/dates
        if event.start:
            if event.start.dateTime:
                try:
                    start_dt = date_parser.isoparse(event.start.dateTime)
                    event_date = start_dt.date()
                except ValueError: logger.warning(f"Could not parse start dateTime: {event.start.dateTime}"); continue
            elif event.start.date:
                try:
                    event_date = date_parser.parse(event.start.date).date()
                    # All-day events don't have a specific duration from start/end times typically
                except ValueError: logger.warning(f"Could not parse start date: {event.start.date}"); continue

        if not event_date:
            logger.warning(f"Event '{event.summary}' ({event.id}) missing valid start information. Skipping.")
            continue

        # Ensure the event actually starts within our analysis window bounds
        # (API might return events overlapping the start/end)
        # Need to compare dates correctly (timezone awareness)
        if not (time_min.date() <= event_date < time_max.date()):
             # Basic date check; refine if timezone crossing near midnight is critical
             # logger.debug(f"Skipping event {event.id} starting outside date range: {event_date}")
             continue

        # Increment event count for the date
        busyness_by_date[event_date]['event_count'] += 1

        # Calculate duration for non-all-day events
        if start_dt and event.end and event.end.dateTime:
            try:
                end_dt = date_parser.isoparse(event.end.dateTime)
                duration = end_dt - start_dt
                # Add duration in minutes, handle potential negative duration if times are swapped?
                busyness_by_date[event_date]['total_duration_minutes'] += max(0, duration.total_seconds() / 60.0)
            except ValueError:
                logger.warning(f"Could not parse end dateTime: {event.end.dateTime} for event {event.id}")
            except TypeError:
                logger.warning(f"Could not calculate duration for event {event.id} (start: {start_dt}, end: {end_dt})")


    # Fill in days with zero events within the range?
    # Optional: Iterate from time_min.date() to time_max.date() and ensure all keys exist
    # current_date = time_min.date()
    # while current_date < time_max.date():
    #     if current_date not in busyness_by_date:
    #         busyness_by_date[current_date] = {'event_count': 0, 'total_duration_minutes': 0.0}
    #     current_date += timedelta(days=1)

    # Convert defaultdict back to regular dict and sort by date
    sorted_busyness = dict(sorted(busyness_by_date.items()))

    logger.info(f"Finished busyness analysis. Analyzed {len(sorted_busyness)} days.")
    return sorted_busyness 