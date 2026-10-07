"""Canvas sizes and subject-aware crops shared by previews and final renders."""


def canvas_size(brand, preview=False):
    width, height = brand['video']['width'], brand['video']['height']
    if width != 1080 or height not in (1350, 1920):
        raise ValueError('Use a 1080x1350 (4:5) or 1080x1920 (9:16) design canvas.')
    if preview:
        return (576, 720) if height == 1350 else (540, 960)
    return width, height


def crop_rect(source_width, source_height, width, height, center):
    ratio = width / height
    if source_width / source_height > ratio:
        cw, ch = round(source_height * ratio / 2) * 2, source_height
    else:
        cw, ch = source_width, round(source_width / ratio / 2) * 2
    cw, ch = min(source_width, cw), min(source_height, ch)
    x = max(0, min(source_width - cw, round((source_width * center[0] - cw / 2) / 2) * 2))
    y = max(0, min(source_height - ch, round((source_height * center[1] - ch / 2) / 2) * 2))
    return x, y, cw, ch
