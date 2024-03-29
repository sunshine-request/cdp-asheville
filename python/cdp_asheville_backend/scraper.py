#!/usr/bin/env python
# -*- coding: utf-8 -*-
import pytz

from datetime import datetime

# from typing import List

# from cdp_backend.pipeline.ingestion_models import EventIngestionModel

###############################################################################
import logging
import json
from yt_dlp import YoutubeDL, DateRange

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
        user_agent_string = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) "
        user_agent_string += "AppleWebKit/537.36 (KHTML, like Gecko) "
        user_agent_string += "Chrome/35.0.1916.47 Safari/537.36"
        req = Request(
            url,
            data=None,
            headers={"User-Agent": user_agent_string},
        )
        with urlopen(req) as resp:
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
        return (
            input.replace("?usp=sharing", "")
            .replace("/view", "")
            .replace("file/d/", "uc?export=download&id=")
        )

    def get_council_meeting_events(self, item: dict) -> Optional[List[Session]]:
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
        events = []

        if item["acf"] is None:
            return events

        if item["acf"]["meeting_videos"] is None:
            return events

        for video in item["acf"]["meeting_videos"]:
            sessions: List[Session] = []
            session_index = 0

            if video["video_url"] is not None:
                processed_video_url = self.process_youtube_url(video["video_url"])
                video_label = video["video_label"]

                try:
                    ydl_opts = {}
                    with YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(processed_video_url, download=False)

                        if info["release_timestamp"] is not None:
                            event_release_timestamp = info["release_timestamp"]
                            event_date = datetime.fromtimestamp(
                                event_release_timestamp, pytz.timezone("UTC")
                            )

                            # Alternative Approach
                            # event_date_string = info["upload_date"]
                            # parse date in format 20230518
                            # event_date = datetime.strptime(
                            # event_date_string, "%Y%m%d"
                            # ).replace(tzinfo=pytz.UTC)

                            sessions.append(
                                self.get_none_if_empty(
                                    Session(
                                        session_datetime=self.localize_datetime(
                                            event_date
                                        ),
                                        session_index=session_index,
                                        video_uri=processed_video_url,
                                        caption_uri=None,
                                    )
                                )
                            )

                            body_name = "Asheville City Council: "
                            body_name += video_label

                            agenda_url = None
                            minutes_url = item["acf"]["meeting_minutes"]

                            if video_label == "City Council Meeting":
                                agenda_url = item["acf"]["meeting_agenda"]
                            elif video_label == "Agenda Briefing":
                                agenda_url = item["acf"]["meeting_agenda_briefing"]

                            if agenda_url is not None:
                                agenda_url = self.process_drive_link(agenda_url)

                            if minutes_url is not None:
                                minutes_url = self.process_drive_link(minutes_url)

                            events.append(
                                self.get_none_if_empty(
                                    EventIngestionModel(
                                        body=Body(name=body_name),
                                        agenda_uri=agenda_url,
                                        minutes_uri=minutes_url,
                                        # event_minutes_items=self.get_event_minutes(event_page.soup),
                                        sessions=sessions,
                                    )
                                )
                            )

                            # session_index += 1

                except BaseException as e:
                    log.error(f"Failed to open {processed_video_url}: {str(e)}")

        return reduced_list(events)

    def process_youtube_url(self, input: str) -> str:
        input = input.replace(
            "https://youtube.com/live/", "https://www.youtube.com/watch?v="
        )

        input = input.replace(
            "https://www.youtube.com/live/", "https://www.youtube.com/watch?v="
        )

        input = input.replace("https://youtu.be/", "https://www.youtube.com/watch?v=")

        # https://www.youtube.com/embed/9giQGUCV9d0?modestbranding=1&hd=1&vq=hd720&rel=0&playsinline=1
        input = input.replace("?modestbranding=1&hd=1&vq=hd720&rel=0&playsinline=1", "")
        input = input.replace(
            "https://www.youtube.com/embed/", "https://www.youtube.com/watch?v="
        )

        input = input.replace("?feature=share", "")

        # Cut any text after & symbol
        input = input.split("&")[0]

        if input == "https://www.youtube.com/user/CityofAsheville/featured":
            return None

        if "youtube.com" in input:
            return input
        else:
            return None

    def get_events_for_board(
        self,
        board_page: BeautifulSoup,
        start_date_time: datetime,
        end_date_time: datetime,
    ) -> Optional[List[EventIngestionModel]]:
        events: List[EventIngestionModel] = []

        if board_page is None:
            return

        board_name_elm = board_page.find("h2", attrs={"class": "entry-title"})

        if board_name_elm is None:
            return

        board_name = board_name_elm.text

        meeting_table = board_page.find("tbody")

        if meeting_table is None:
            return

        meeting_rows = meeting_table.find_all("tr")

        for meeting_row in meeting_rows:
            # print(meeting_row)

            meeting_row_tds = meeting_row.find_all("td")

            if len(meeting_row_tds) < 3:
                continue

            meeting_agenda_td = meeting_row_tds[0]
            # meeting_docs_td = meeting_row_tds[1]
            meeting_video_td = meeting_row_tds[2]

            event_date_str = None
            agenda_uri = None

            if meeting_video_td is not None:
                meeting_video_link = meeting_video_td.find("a")

            if meeting_agenda_td is not None:
                meeting_agenda_link = meeting_agenda_td.find("a")
                if meeting_agenda_link is not None:
                    event_date_str = meeting_agenda_link.text.replace("Agenda", "")
                    event_date_str = event_date_str.replace("Special Meeting", "")
                    event_date_str = event_date_str.replace("Presentation Schedule", "")
                    event_date_str = event_date_str.replace("– Staff Report", "")
                    event_date_str = event_date_str.replace(" –", "")
                    event_date_str = event_date_str.replace("(Updated)", "")
                    event_date_str = event_date_str.replace("Updated", "")
                    event_date_str = event_date_str.replace(
                        "Joint Audit Committee Meeting", ""
                    )
                    event_date_str = event_date_str.replace(
                        "work session w/ Multimodal Transportation Commission", ""
                    )
                    event_date_str = event_date_str.replace("   ", " ")
                    event_date_str = event_date_str.replace("  ", " ")
                    event_date_str = event_date_str.strip()
                    meeting_agenda_url = meeting_agenda_link["href"]
                    agenda_uri = self.process_drive_link(meeting_agenda_url)
                    # print(meeting_agenda_url)

            if event_date_str is None or meeting_video_link is None:
                continue

            event_date_str = event_date_str.replace(",", ", ").replace(",", "")
            event_date_str = event_date_str.replace("  ", " ")
            event_date_str = event_date_str.replace("Retreat", "")

            try:
                event_date = datetime.strptime(event_date_str, "%B %d %Y").replace(
                    tzinfo=pytz.UTC
                )

            except ValueError:
                print("Exception")
                print(event_date_str)
                continue

            if not (start_date_time < event_date < end_date_time):
                continue

            sessions: List[Session] = []
            session_index = 0

            video_uri = meeting_video_link["href"]

            # video_uri contains("publicinput.com")
            if "publicinput.com" in video_uri:
                public_input_page = load_web_page(video_uri)
                if public_input_page is not None:
                    video_iframe = public_input_page.soup.find("iframe")
                    if video_iframe is not None:
                        video_uri = video_iframe["src"]

            processed_video_url = self.process_youtube_url(video_uri)

            if processed_video_url is not None:
                print("Processed video URL: " + processed_video_url)

                try:
                    ydl_opts = {}
                    with YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(processed_video_url, download=False)

                        if info["release_timestamp"] is not None:
                            event_release_timestamp = info["release_timestamp"]
                            event_date = datetime.fromtimestamp(
                                event_release_timestamp, pytz.timezone("UTC")
                            )

                            sessions.append(
                                self.get_none_if_empty(
                                    Session(
                                        session_datetime=self.localize_datetime(
                                            event_date
                                        ),
                                        session_index=session_index,
                                        video_uri=processed_video_url,
                                        caption_uri=None,
                                    )
                                )
                            )

                            events.append(
                                self.get_none_if_empty(
                                    EventIngestionModel(
                                        agenda_uri=agenda_uri,
                                        body=Body(name=board_name),
                                        # event_minutes_items=self.get_event_minutes(event_page.soup),
                                        # minutes_uri=None,
                                        sessions=sessions,
                                    )
                                )
                            )

                except BaseException as e:
                    log.error(f"Failed to open {processed_video_url}: {str(e)}")

        return reduced_list(events)

    def get_boards(
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
        events = []

        board_tables = event_page.find_all("tbody")

        board_table = board_tables[1]

        board_rows = board_table.find_all("tr")
        # board_rows = [board_table.find('tr')]

        for board_row in board_rows:
            board_link = board_row.find("td").find("a")
            if board_link is not None:
                board_page = load_web_page(board_link["href"])

                # print(board_link["href"])

                if board_page is not None:
                    new_events = self.get_events_for_board(
                        board_page.soup, start_date_time, end_date_time
                    )

                    if new_events is not None:
                        events += new_events

        return events

    def load_board_and_commission_page(
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
            "https://www.ashevillenc.gov/department/city-clerk/boards-and-commissions/"
        )

        if not event_page.status:
            return None

        return self.get_boards(event_page.soup, start_date_time, end_date_time)

    def filter_upcoming_events(info, *, incomplete):
        """Download only videos longer than a minute (or with unknown duration)"""
        live_status = info.get("live_status")
        # print(live_status)
        if live_status == "is_upcoming":
            return "The video is is_upcoming"

    def get_events_from_youtube_channel(
        self,
        start_date_time: datetime,
        end_date_time: datetime,
    ) -> Optional[List[EventIngestionModel]]:
        print("Load YouTube Channel")

        # url = "https://www.youtube.com/@CityofAsheville/streams"
        url = (
            "https://www.youtube.com/@CityofAsheville/search?query=before%3A"
            + end_date_time.strftime("%Y-%m-%d")
        )
        url += "%20%2Bafter%3A" + start_date_time.strftime("%Y-%m-%d")
        # url += "%20%2Blive"

        # Create DateRange with start and end date in format YYYYMMDD
        daterange = DateRange(
            start_date_time.strftime("%Y%m%d"), end_date_time.strftime("%Y%m%d")
        )

        ydl_opts = {
            "match_filter": self.filter_upcoming_events,
            "daterange": daterange,
            "ignoreerrors": True
            # 'date_before' : end_date_time,
            # 'date_after' : start_date_time,
        }

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            # print("Found Video")
            # print(info)
            return info

    def get_board_events_from_youtube(
        self,
        start_date_time: datetime,
        end_date_time: datetime,
    ) -> Optional[List[EventIngestionModel]]:
        events = []

        youtube_data = self.get_events_from_youtube_channel(
            start_date_time, end_date_time
        )

        for video in youtube_data["entries"]:
            sessions: List[Session] = []
            session_index = 0

            # PRC 08.2203
            if video is None:
                continue

            # TODO: Check video["live_status"]

            title = video["title"]

            board_name = title.split("–")[0].strip()

            processed_video_url = video["original_url"]

            # if "City Council" in board_name:
            # print("City Council FOUND")
            # continue

            if video["release_timestamp"] is not None:
                event_release_timestamp = video["release_timestamp"]
                event_date = datetime.fromtimestamp(
                    event_release_timestamp, pytz.timezone("UTC")
                )

                sessions.append(
                    self.get_none_if_empty(
                        Session(
                            session_datetime=self.localize_datetime(event_date),
                            session_index=session_index,
                            video_uri=processed_video_url,
                            caption_uri=None,
                        )
                    )
                )

                events.append(
                    self.get_none_if_empty(
                        EventIngestionModel(
                            # agenda_uri=agenda_uri,
                            body=Body(name=board_name),
                            # event_minutes_items=self.get_event_minutes(event_page.soup),
                            # minutes_uri=None,
                            sessions=sessions,
                        )
                    )
                )

        return events

    def load_council_meeting_materials_rest(
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

        # Load JSON from REST ENDPOINT
        # https://www.ashevillenc.gov/wp-json/wp/v2/meetings/
        city_council_mettings_endpoint = (
            "https://www.ashevillenc.gov/wp-json/wp/v2/meetings/"
        )

        city_council_mettings_endpoint_url = city_council_mettings_endpoint
        city_council_mettings_endpoint_url += (
            "?modified_after=" + start_date_time.isoformat()
        )
        city_council_mettings_endpoint_url += (
            "&modified_before=" + end_date_time.isoformat()
        )
        city_council_mettings_endpoint_url = city_council_mettings_endpoint_url.replace(
            "+00:00", ""
        )

        print("Get Council Meeting Materials: " + city_council_mettings_endpoint_url)

        events = []
        try:
            with urlopen(city_council_mettings_endpoint_url) as resp:
                response = resp.read()
                # data = response.json()
                data = json.loads(response.decode("utf-8"))

                if data is not None:
                    for item in data:
                        council_events = self.get_council_meeting_events(item)
                        if council_events is not None:
                            events += council_events

        except URLError or HTTPError as e:
            log.error(f"Failed to open {city_council_mettings_endpoint}: {str(e)}")

        return events

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

        start_date = from_dt.replace(tzinfo=pytz.UTC)

        end_date = to_dt.replace(tzinfo=pytz.UTC)

        # Your implementation here
        # board_events = self.load_board_and_commission_page(start_date, end_date)
        board_events = self.get_board_events_from_youtube(start_date, end_date)
        events = self.load_council_meeting_materials_rest(start_date, end_date)

        if board_events is not None:
            events += board_events

        # Future - Pull events from other sources

        # print(events)
        return events


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


###############################################################################
# Allow caller to directly run this module (usually in development scenarios)

if __name__ == "__main__":
    # start_date_time = datetime(2022, 10, 1)
    # end_date_time = datetime(2021, 10, 4)
    from_dt = "2023-07-29"

    start_date_time = datetime.fromisoformat(from_dt)

    # start_date_time = datetime.fromisoformat("2021-09-26T02:44:36+0000")
    end_date_time = datetime.fromisoformat("2023-08-19")

    # start_date_time = datetime(2021, 9, 26)
    # end_date_time = datetime(2021, 9, 29)

    scraper = AshevilleScraper()

    asheville_events = scraper.get_events(start_date_time, end_date_time)
    print(asheville_events)
