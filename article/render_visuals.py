from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
WIDTH = 1600
HEIGHT = 900


def font(size, bold=False):
    candidates = [
        (
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
            if bold
            else "/System/Library/Fonts/Supplemental/Arial.ttf"
        ),
        (
            "/Library/Fonts/Arial Bold.ttf"
            if bold
            else "/Library/Fonts/Arial.ttf"
        ),
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


TITLE = font(42, True)
SUBTITLE = font(18)
BRAND = font(24, True)
HEADING = font(22, True)
BODY = font(15)
SMALL = font(13)
METRIC = font(30, True)


def wrapped(draw, position, text, selected_font, fill, width, spacing=5):
    words = text.split()
    lines = []
    current = []
    for word in words:
        candidate = " ".join(current + [word])
        if draw.textlength(candidate, font=selected_font) <= width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    draw.multiline_text(
        position,
        "\n".join(lines),
        font=selected_font,
        fill=fill,
        spacing=spacing,
    )


def box(draw, xy, fill, outline, radius=8, width=2):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def arrow(draw, x1, y, x2, color="#747d8c"):
    draw.line((x1, y, x2 - 14, y), fill=color, width=4)
    draw.polygon(
        [(x2, y), (x2 - 15, y - 9), (x2 - 15, y + 9)],
        fill=color,
    )


def node(draw, x, y, w, h, title, body, fill, outline):
    box(draw, (x, y, x + w, y + h), fill, outline, radius=7, width=3)
    wrapped(draw, (x + 17, y + 15), title, font(17, True), "#181b22", w - 34)
    wrapped(draw, (x + 17, y + 48), body, SMALL, "#5d6675", w - 34, spacing=3)


def render_architecture():
    image = Image.new("RGB", (WIDTH, HEIGHT), "#f7f8fb")
    draw = ImageDraw.Draw(image)

    draw.text((64, 42), "kestra.", font=BRAND, fill="#6d36d8")
    draw.text(
        (64, 78),
        "Three retry policies, one downstream limit",
        font=TITLE,
        fill="#171a20",
    )
    wrapped(
        draw,
        (1030, 66),
        "Thirty Subflow executions recover from the same eight-second outage. "
        "Only the layered path coordinates network dispatch.",
        SUBTITLE,
        "#596171",
        500,
        spacing=4,
    )
    draw.line((64, 150, 1536, 150), fill="#d9dde7", width=2)

    labels = [
        (
            "1. Local retries",
            "Independent clocks synchronize retry waves.",
            "#d94c4c",
        ),
        (
            "2. Bulkhead only",
            "Five active executions, but no request-rate contract.",
            "#df8c20",
        ),
        (
            "3. Layered policy",
            "Bulkhead, circuit, budget, and durable dispatch.",
            "#27956d",
        ),
    ]
    nodes = [
        (
            ("30 executions", "Exponential HTTP retries", "#f8f4ff", "#8151dc"),
            ("Independent clocks", "Wake and retry together", "#fff5f5", "#d94c4c"),
            ("30 req/s peak", "70 overload responses", "#fff5f5", "#d94c4c"),
        ),
        (
            ("Queued work", "Kestra behavior: QUEUE", "#f8f4ff", "#8151dc"),
            ("Five active", "Controls work in flight", "#fff9ef", "#df8c20"),
            ("10 req/s peak", "40 overload responses", "#fff9ef", "#df8c20"),
        ),
        (
            ("Five active", "LoopUntil asks permission", "#f8f4ff", "#8151dc"),
            ("Circuit + budget", "One probe; 4 permits/s", "#f2fbf7", "#27956d"),
            ("Dispatch slots", "250 ms network spacing", "#f2fbf7", "#27956d"),
        ),
    ]
    provider_notes = [
        ("Fault-injection API", "8 s outage\nCapacity: 5 req/s", "#d94c4c"),
        ("Same provider", "Concurrency is not\nrate limiting", "#df8c20"),
        ("Same provider", "4 req/s peak\n0 overload responses", "#27956d"),
    ]

    lane_y = [180, 370, 560]
    for index, y in enumerate(lane_y):
        color = labels[index][2]
        box(draw, (64, y, 294, y + 150), "#ffffff", "#dfe3eb")
        draw.rectangle((64, y, 70, y + 150), fill=color)
        wrapped(draw, (84, y + 22), labels[index][0], HEADING, "#181b22", 190)
        wrapped(draw, (84, y + 60), labels[index][1], BODY, "#626b79", 190)

        box(draw, (320, y, 1210, y + 150), "#ffffff", "#dfe3eb")
        node_x = [344, 646, 948]
        for node_index, x in enumerate(node_x):
            title, body, fill, outline = nodes[index][node_index]
            node(draw, x, y + 28, 220, 94, title, body, fill, outline)
        arrow(draw, 570, y + 75, 638)
        arrow(draw, 872, y + 75, 940)

        box(draw, (1236, y, 1536, y + 150), "#ffffff", "#303948", width=2)
        provider_title, provider_body, provider_color = provider_notes[index]
        wrapped(draw, (1260, y + 27), provider_title, HEADING, "#181b22", 250)
        draw.multiline_text(
            (1260, y + 69),
            provider_body,
            font=BODY,
            fill=provider_color,
            spacing=6,
        )
        arrow(draw, 1210, y + 75, 1236)

    state_y = 748
    box(draw, (64, state_y, 294, 852), "#242a35", "#242a35")
    wrapped(
        draw,
        (84, state_y + 29),
        "PostgreSQL shared state",
        HEADING,
        "#ffffff",
        190,
    )
    box(draw, (320, state_y, 1210, 852), "#edf8f3", "#27956d", width=3)
    state_items = [
        ("Circuit", "CLOSED / OPEN / HALF_OPEN"),
        ("Probe lease", "One recovery owner"),
        ("Retry budget", "Atomic admission"),
        ("Decision ledger", "Append-only evidence"),
    ]
    for index, (title, body) in enumerate(state_items):
        x = 344 + index * 213
        draw.rectangle((x, state_y + 22, x + 4, state_y + 82), fill="#55aa89")
        draw.text((x + 16, state_y + 24), title, font=font(16, True), fill="#1a3f33")
        wrapped(draw, (x + 16, state_y + 52), body, SMALL, "#4c675d", 175)
    box(draw, (1236, state_y, 1536, 852), "#ffffff", "#27956d", width=3)
    wrapped(
        draw,
        (1260, state_y + 24),
        "Kestra owns orchestration. PostgreSQL owns atomic coordination.",
        font(17, True),
        "#1b654d",
        250,
        spacing=5,
    )

    image.save(ROOT / "architecture.png", quality=96)


def render_results():
    image = Image.new("RGB", (WIDTH, HEIGHT), "#f7f8fb")
    draw = ImageDraw.Draw(image)

    draw.text((72, 48), "kestra.", font=BRAND, fill="#6d36d8")
    draw.text((72, 84), "Recovery traffic became the failure", font=TITLE, fill="#171a20")
    wrapped(
        draw,
        (1050, 66),
        "Clean Docker run, 30 clients, eight-second outage, "
        "five-request/s downstream capacity.",
        SUBTITLE,
        "#596171",
        470,
        spacing=4,
    )
    draw.line((72, 158, 1528, 158), fill="#d9dde7", width=2)

    columns = [72, 340, 1050, 1200, 1370]
    headers = ["Strategy", "Total requests", "Peak RPS", "Amplification", "Overload"]
    for x, header in zip(columns, headers):
        draw.text((x, 186), header.upper(), font=font(13, True), fill="#697282")

    rows = [
        (
            "Independent retries",
            "Thirty execution-local retry clocks",
            231,
            30,
            "7.70x",
            70,
            "#d94c4c",
        ),
        (
            "Bulkhead only",
            "Five active executions; remaining work queued",
            100,
            10,
            "3.33x",
            40,
            "#df8c20",
        ),
        (
            "Layered policy",
            "Bulkhead, circuit, budget, dispatch slots",
            44,
            4,
            "1.47x",
            0,
            "#27956d",
        ),
    ]
    row_y = [238, 416, 594]
    for row, y in zip(rows, row_y):
        title, subtitle, requests, peak, amplification, overload, color = row
        draw.line((72, y - 18, 1528, y - 18), fill="#dfe3eb", width=1)
        wrapped(draw, (72, y + 18), title, HEADING, "#181b22", 235)
        wrapped(draw, (72, y + 57), subtitle, BODY, "#667080", 235)

        track_x = 340
        track_y = y + 35
        track_w = 650
        draw.rectangle((track_x, track_y, track_x + track_w, track_y + 54), fill="#e8ebf1")
        bar_w = max(90, int(track_w * requests / 231))
        draw.rectangle((track_x, track_y, track_x + bar_w, track_y + 54), fill=color)
        request_text = str(requests)
        text_width = draw.textlength(request_text, font=font(19, True))
        draw.text(
            (track_x + bar_w - text_width - 14, track_y + 15),
            request_text,
            font=font(19, True),
            fill="#ffffff",
        )

        draw.text((1050, y + 30), str(peak), font=METRIC, fill="#181b22")
        draw.text((1050, y + 68), "requests/s", font=SMALL, fill="#687181")
        draw.text((1200, y + 30), amplification, font=METRIC, fill="#181b22")
        draw.text((1200, y + 68), "requests/success", font=SMALL, fill="#687181")
        overload_color = "#237a5c" if overload == 0 else "#181b22"
        draw.text((1370, y + 30), str(overload), font=METRIC, fill=overload_color)
        draw.text((1370, y + 68), "responses", font=SMALL, fill="#687181")

    draw.line((72, 770, 1528, 770), fill="#d9dde7", width=2)
    footer = [
        ("30 / 30", "clients completed in every scenario"),
        ("81%", "fewer requests than independent retries"),
        ("11.685 s", "recovery delay with layered control"),
    ]
    for index, (metric, label) in enumerate(footer):
        x = 72 + index * 490
        draw.rectangle((x, 800, x + 5, 858), fill="#6d36d8")
        draw.text((x + 18, 794), metric, font=font(25, True), fill="#181b22")
        draw.text((x + 18, 833), label, font=BODY, fill="#616a79")

    image.save(ROOT / "results.png", quality=96)


if __name__ == "__main__":
    render_architecture()
    render_results()

