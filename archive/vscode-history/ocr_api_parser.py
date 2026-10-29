import requests
import re

API_KEY = "helloworld"  # besplatni demo key

def parse_offer_screenshot(uploaded_image):

    url = "https://api.ocr.space/parse/image"

    response = requests.post(
        url,
        files={"filename": uploaded_image},
        data={
            "apikey": API_KEY,
            "language": "eng"
        }
    )

    result = response.json()

    if "ParsedResults" not in result:
        return []

    raw_text = result["ParsedResults"][0]["ParsedText"]

    lines = raw_text.split("\n")

    parsed_data = []

    for line in lines:

        match = re.findall(r"([A-Za-z\s\.-]+)\s+(\d+\.\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)", line)

        if match:
            name, line_value, over_odds, under_odds = match[0]

            parsed_data.append(
                (
                    name.strip(),
                    float(line_value),
                    float(over_odds),
                    float(under_odds)
                )
            )

    return parsed_data
