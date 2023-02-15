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

from cdp_backend.utils import file_utils

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import WebVTTFormatter


class TranscriptSentenceModifier:
    def __init__(self):
        super().__init__()

    def translate_transcript_file(
        self, video_id: str, original_transcript_file_name: str
    ) -> Optional[str]:
        import spacy
        import en_core_web_lg  # noqa: F401

        nlp = spacy.load("en_core_web_lg")

        intermediate_transcript_file_name = "intermediate.vtt"
        output_transcript_file_name = video_id + "-caption-outupt.vtt"

        with open(original_transcript_file_name) as f:
            full_transcript_file = f.read()

        pattern = re.compile(
            r"^\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}", re.MULTILINE
        )

        text = full_transcript_file

        text = re.sub(pattern, "", text)

        doc = nlp(text)

        with open(intermediate_transcript_file_name, "w") as f:
            for sent in doc.sents:
                sentence_text = sent.text.capitalize() + ". "
                # sentence_text = sentence_text.replace(" .", ".")
                f.write(sentence_text)
                # f.write("\n")

        with open(intermediate_transcript_file_name) as f:
            intermediate_transcript_file = f.readlines()

        with open(original_transcript_file_name) as f:
            original_transcript_file = f.readlines()

        with open(output_transcript_file_name, "w") as f:
            line_number = 0
            for line in intermediate_transcript_file:
                if line_number < len(original_transcript_file) and re.match(
                    pattern, original_transcript_file[line_number]
                ):
                    f.write(original_transcript_file[line_number])
                elif line_number == 0:
                    f.write(original_transcript_file[line_number])
                else:
                    processed_intermediate_line = intermediate_transcript_file[
                        line_number
                    ]

                    processed_intermediate_line = processed_intermediate_line.replace(
                        ". ", ".\n"
                    )

                    f.write(processed_intermediate_line)

                line_number += 1

        return output_transcript_file_name


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
        return (
            input.replace("?usp=sharing", "")
            .replace("/view", "")
            .replace("file/d/", "uc?export=download&id=")
        )

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
            processed_video_url = session_video_link["href"].replace(
                "https://youtu.be/", "https://www.youtube.com/watch?v="
            )

            # PRC 02.2023 - More processing of URLs
            processed_video_url = processed_video_url.replace("https://youtube.com/live/", "https://www.youtube.com/watch?v=")

            processed_video_url = processed_video_url.replace("?feature=share", "")

            print("Processed video URL: " + processed_video_url)

            caption_uri = self.get_captions(processed_video_url)

            sessions.append(
                self.get_none_if_empty(
                    Session(
                        session_datetime=self.localize_datetime(event_date),
                        session_index=session_index,
                        video_uri=processed_video_url,
                        caption_uri=caption_uri,
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

            if month_element is None:
                continue

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

            try:
                event_date = datetime.strptime(event_date_str, "%B %d %Y")

            except ValueError:
                print("Exception")
                print(event_date_str)
                continue

            if not (start_date_time < event_date < end_date_time):
                continue

            sessions: List[Session] = []
            session_index = 0

            processed_video_url = meeting_video_link["href"].replace(
                "https://youtu.be/", "https://www.youtube.com/watch?v="
            )
            caption_uri = self.get_captions(processed_video_url)

            # Note: It looks like the shortened URL video links cause a validation error
            # when adding to firestore. Should open an issue on cdp-backend
            sessions.append(
                self.get_none_if_empty(
                    Session(
                        session_datetime=self.localize_datetime(event_date),
                        session_index=session_index,
                        video_uri=processed_video_url,
                        caption_uri=caption_uri,
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

        board_table = event_page.find("tbody")

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
        board_events = self.load_board_and_commission_page(from_dt, to_dt)
        events = self.load_council_meeting_materials_page(from_dt, to_dt)

        if board_events is not None:
            events += board_events

        # Future - Pull events from other sources

        # print(events)
        return events

    def get_captions(
        self,
        uri: str,
        **kwargs,
    ) -> Optional[str]:
        print("Captions disabled")
        return None

        print("Download Subtitle: " + uri)

        if "https://www.youtube.com/watch?v=" not in str(uri):
            print("Not youtube, skip caption download")
            return None

        # Ensure dest isn't a file
        # if dst.is_file() and not overwrite:
        #     raise FileExistsError(dst)

        video_id = uri.replace("https://www.youtube.com/watch?v=", "")

        subtitle_download_dst = video_id + "subtitle-dl.en.vtt"
        subtitle_copy_dst = video_id + "subtitle.en.vtt"

        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        formatter = WebVTTFormatter()
        vtt_formatted = formatter.format_transcript(transcript)

        with open(subtitle_download_dst, "w", encoding="utf-8") as vtt_file:
            vtt_file.write(vtt_formatted)

        sentence_transformer = TranscriptSentenceModifier()
        processed_transcript_file = sentence_transformer.translate_transcript_file(
            video_id=video_id, original_transcript_file_name=subtitle_download_dst
        )

        if processed_transcript_file is None:
            return None

        resource_copy_filepath = file_utils.resource_copy(
            uri=processed_transcript_file,
            dst=subtitle_copy_dst,
            overwrite=True,
        )

        return resource_copy_filepath

        # if False:
        #     from yt_dlp import YoutubeDL

        #     ydl_opts = {
        #         "outtmpl": subtitle_download_dst,
        #         "subtitleslangs": ["en"],
        #         "skip_download": True,
        #         "writesubtitles": True,
        #         "writeautomaticsub": True,
        #         # "subtitlesformat" : "vtt"
        #     }
        #     with YoutubeDL(ydl_opts) as ydl:
        #         ydl.download([uri])

        #         with open(subtitle_download_dst + ".en.vtt", "r+") as f:
        #             new_f = f.readlines()
        #             f.seek(0)
        #             for line in new_f:
        #                 if "Kind: captions" not in line:
        #                     if "Language: en" not in line:
        #                         f.write(line)
        #             f.truncate()

        #         resource_copy_filepath = file_utils.resource_copy(
        #             uri=subtitle_download_dst + ".en.vtt",
        #             dst=subtitle_copy_dst,
        #             overwrite=True,
        #         )

        #         return resource_copy_filepath


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


###############################################################################
# Allow caller to directly run this module (usually in development scenarios)

if __name__ == "__main__":
    start_date_time = datetime(2022, 10, 1)
    end_date_time = datetime(2021, 10, 4)

    scraper = AshevilleScraper()
    asheville_events = scraper.get_events(start_date_time, end_date_time)
    print(asheville_events)
