#!/usr/bin/env python
# -*- coding: utf-8 -*-

from datetime import datetime

# from typing import List

# from cdp_backend.pipeline.ingestion_models import EventIngestionModel

###############################################################################
from dateutil.rrule import rrule, MONTHLY

import logging

from cdp_scrapers.scraper_utils import (
    IngestionModelScraper,
    reduced_list,
    # str_simplified,
    # parse_static_file,
)


from cdp_backend.pipeline.ingestion_models import (
    Body,
    EventIngestionModel,
    # EventMinutesItem,
    # Matter,
    # MinutesItem,
    # Person,
    Session,
    # SupportingFile,
    # Vote,
)

log = logging.getLogger(__name__)

###############################################################################
import re

# from typing import Any, List, NamedTuple, Optional, Union
from typing import List, NamedTuple, Optional, Union
from bs4 import BeautifulSoup
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class WebPageSoup(NamedTuple):
    status: bool
    soup: Optional[BeautifulSoup] = None


def load_web_page(url: Union[str, Request]) -> WebPageSoup:
    """
    Load web page at url and return content soupified

    Parameters
    ----------
    url: str | urllib.request.Request
        Web page to load

    Returns
    -------
    result: WebPageSoup
        WebPageSoup.status = False if web page at url could not be loaded

    """
    try:
        with urlopen(url) as resp:
            return WebPageSoup(True, BeautifulSoup(resp.read(), "html.parser"))
    except URLError or HTTPError as e:
        log.error(f"Failed to open {url}: {str(e)}")

    return WebPageSoup(False)


###############################################################################


class AshevilleScraper(IngestionModelScraper):
    def __init__(self):
        super().__init__(timezone="America/New_York")

    def process_drive_link(self, input: str) -> str:
        # https://drive.google.com/file/d/1CgJk-55n1ujfYc8-F1U-Rw7YwUdtdZ4P/view
        # https://drive.google.com/uc?export=download&id=1CgJk-55n1ujfYc8-F1U-Rw7YwUdtdZ4P
        return input.replace("/view", "").replace("file/d/", "uc?export=download&id=")

    def get_sessions(
        self, event_page: BeautifulSoup, event_date: datetime
    ) -> Optional[List[Session]]:
        """
        Parse meeting video URIs from event_page,
        return Session for each video found.

        Parameters
        ----------
        event_page: BeautifulSoup
            Web page for the meeting loaded as a bs4 object

        Returns
        -------
        sessions: Optional[List[Session]]
            Session for each video found on event_page
        """
        # each session's meta data is given in <div class="session-meta">
        # including youtube video url for the session, if available
        # <div class="session-meta">
        # ...
        # <time class="datetime">Wednesday, December 15, 2021 9:30 am</time>
        # ...
        # <iframe src="https://www.youtube.com/...">

        sessions: List[Session] = []
        session_index = 0

        # Note: It looks like the shortened URL video links cause a validation error
        # when adding to firestore. Should open an issue on cdp-backend
        for session_video_link in event_page.find_all("a"):
            sessions.append(
                self.get_none_if_empty(
                    Session(
                        session_datetime=self.localize_datetime(event_date),
                        session_index=session_index,
                        video_uri=session_video_link["href"].replace(
                            "https://youtu.be/", "https://www.youtube.com/watch?v="
                        ),
                    )
                )
            )

            session_index += 1

        return reduced_list(sessions)

    def get_events_for_month_article(
        self,
        soup_article: BeautifulSoup,
        start_date_time: datetime,
        end_date_time: datetime,
        month_date: datetime,
    ) -> Optional[List[EventIngestionModel]]:

        # print("Events for month")

        event_headers = soup_article.find_all("h4")

        events: List[EventIngestionModel] = []

        for event_header in event_headers:
            event_link_elm = event_header.find("a")

            event_month_date = event_link_elm.text.strip()

            event_date_str = event_month_date + " " + month_date.strftime("%Y")
            # event_link = event_link_elm["href"]
            # event_date_str = event_link.rsplit("/", 2)[-2]
            # event_date_str = event_date_str.replace("-", " ").capitalize()
            event_date = datetime.strptime(event_date_str, "%B %d %Y")
            # print(event_date_str)
            # print(event_date)

            # If the event date is out of range, continue
            if not (start_date_time < event_date < end_date_time):
                continue

            event_card = event_header.find_parent("div", attrs={"class": "card"})

            video_header = event_card.find("h5", text=re.compile("Videos"))

            video_container = video_header.find_parent(
                "div", attrs={"class": "container"}
            )

            # video_links = video_container.find_all(
            #     'a'
            # )
            # print(video_links)
            # for video_link in video_links:
            #     video_url = video_link["href"]
            #     event_title = video_link["title"]

            #     event_title += ": " +  event_date.strftime("%B %-d, %Y")

            events.append(
                self.get_none_if_empty(
                    EventIngestionModel(
                        agenda_uri=self.get_agenda_uri(event_card),
                        body=Body(name="Asheville City Council"),
                        # event_minutes_items=self.get_event_minutes(event_page.soup),
                        # minutes_uri=None,
                        minutes_uri=self.get_minutes_uri(event_card),
                        sessions=self.get_sessions(video_container, event_date),
                    )
                )
            )

        return reduced_list(events)

    def get_event(
        self,
        event_page: BeautifulSoup,
        start_date_time: datetime,
        end_date_time: datetime,
    ) -> Optional[EventIngestionModel]:
        """
        Find the uri for the file containing the agenda for a Portland, OR city
        council meeting

        Parameters
        ----------
        event_page: BeautifulSoup
            Web page for the meeting loaded as a bs4 object

        Returns
        -------
        agenda_uri: Optional[str]
            The uri for the file containing the meeting's agenda
        """

        # Get all months between start and end date
        dates = [
            dt for dt in rrule(MONTHLY, dtstart=start_date_time, until=end_date_time)
        ]

        events = []
        for month_date in dates:
            month_date_formatted = month_date.strftime("%B, %Y")
            # print(month_date_formatted)

            month_element = event_page.find("h3", text=re.compile(month_date_formatted))

            month_parent_element = month_element.find_parent("article")

            new_events = self.get_events_for_month_article(
                month_parent_element, start_date_time, end_date_time, month_date
            )

            if new_events is not None:
                events += new_events

        return events

    def get_agenda_uri(self, event_page: BeautifulSoup) -> Optional[str]:
        """
        Find the uri for the file containing the agenda for a Portland, OR city
        council meeting

        Parameters
        ----------
        event_page: BeautifulSoup
            Web page for the meeting loaded as a bs4 object

        Returns
        -------
        agenda_uri: Optional[str]
            The uri for the file containing the meeting's agenda
        """
        agenda_uri_element = event_page.find("a", text=re.compile("Action Agenda"))

        if agenda_uri_element is not None:
            return self.process_drive_link(
                agenda_uri_element["href"].replace("?usp=sharing", "")
            )
        return None

    def get_minutes_uri(self, event_page: BeautifulSoup) -> Optional[str]:
        """
        Find the uri for the file containing the agenda for a Portland, OR city
        council meeting

        Parameters
        ----------
        event_page: BeautifulSoup
            Web page for the meeting loaded as a bs4 object

        Returns
        -------
        agenda_uri: Optional[str]
            The uri for the file containing the meeting's agenda
        """
        agenda_uri_element = event_page.find("a", text=re.compile("Minutes"))

        if agenda_uri_element is not None:
            return self.process_drive_link(
                agenda_uri_element["href"].replace("?usp=sharing", "")
            )
        return None

    def load_council_meeting_materials_page(
        self, start_date_time: datetime, end_date_time: datetime
    ) -> Optional[EventIngestionModel]:
        """
        Portland, OR city council meeting information for a specific date

        Parameters
        ----------
        event_time: datetime
            Meeting date

        Returns
        -------
        Optional[EventIngestionModel]
            None if there was no meeting on event_time
            or information for the meeting did not meet minimal CDP requirements.
        """
        # try to load https://www.portland.gov/council/agenda/yyyy/m/d

        event_page = load_web_page(
            "https://www.ashevillenc.gov/government/city-council-meeting-materials/"
        )

        if not event_page.status:
            return None

        return self.get_event(event_page.soup, start_date_time, end_date_time)

    def get_events(
        self,
        from_dt: datetime,
        to_dt: datetime,
        **kwargs,
    ) -> List[EventIngestionModel]:
        """
        Get all events for the provided timespan.

        Parameters
        ----------
        from_dt: datetime
            Datetime to start event gather from.
        to_dt: datetime
            Datetime to end event gather at.

        Returns
        -------
        events: List[EventIngestionModel]
            All events gathered that occured in the provided time range.

        Notes
        -----
        As the implimenter of the get_events function, you can choose
        to ignore the from_dt and to_dt parameters.
        However, they are useful for manually kicking off pipelines
        from GitHub Actions UI.
        """

        # Your implementation here
        events = self.load_council_meeting_materials_page(from_dt, to_dt)

        # Future - Pull events from other sources

        # print(events)
        return events


####


def get_events(
    from_dt: datetime,
    to_dt: datetime,
    **kwargs,
) -> List[EventIngestionModel]:
    """
    Get all events for the provided timespan.

    Parameters
    ----------
    from_dt: datetime
        Datetime to start event gather from.
    to_dt: datetime
        Datetime to end event gather at.

    Returns
    -------
    events: List[EventIngestionModel]
        All events gathered that occured in the provided time range.

    Notes
    -----
    As the implimenter of the get_events function, you can choose
    to ignore the from_dt and to_dt parameters.
    However, they are useful for manually kicking off pipelines
    from GitHub Actions UI.
    """

    # Your implementation here
    scraper = AshevilleScraper()
    return scraper.get_events(from_dt, to_dt)


dev = False
# FOR DEV, Uncomment line below, then run python scraper.py
dev = True
if dev:
    start_date_time = datetime(2021, 8, 1)
    end_date_time = datetime(2021, 8, 31)

    scraper = AshevilleScraper()
    asheville_events = scraper.get_events(start_date_time, end_date_time)
    print(asheville_events)
