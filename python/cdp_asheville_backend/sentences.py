from typing import Optional
import sys
import re
import spacy


class TranscriptSentenceModifier:
    def __init__(self):
        super().__init__()

    def translate_transcript_file(
        self, video_id: str, original_transcript_file_name: str
    ) -> Optional[str]:

        nlp = spacy.load("en_core_web_lg")

        intermediate_transcript_file_name = "intermediate.vtt"
        output_transcript_file_name = "outupt.vtt"

        with open(original_transcript_file_name) as f:
            full_transcript_file = f.read()

        pattern = re.compile(
            "^\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}", re.MULTILINE
        )

        text = full_transcript_file

        text = re.sub(pattern, "", text)

        doc = nlp(text)

        with open(intermediate_transcript_file_name, "w") as f:
            for sent in doc.sents:
                f.write(sent.text.capitalize() + ". ")
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
                    f.write(intermediate_transcript_file[line_number])

                line_number += 1
