import re

def parse_offer_file(uploaded_file):

    content = uploaded_file.read().decode("utf-8")

    pattern = re.findall(
        r"\d+\.\s+(.*?)\s+Last 5:.*?Line:\s+(\d+\.\d+)\s+Over:\s+(\d+\.\d+)\s+Under:\s+(\d+\.\d+)",
        content,
        re.DOTALL
    )

    parsed_data = []

    for name, line_value, over_odds, under_odds in pattern:
        parsed_data.append(
            (
                name.strip(),
                float(line_value),
                float(over_odds),
                float(under_odds)
            )
        )

    return parsed_data
