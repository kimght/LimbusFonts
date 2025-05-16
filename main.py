import msgspec
import fontforge
import json
import hashlib
import base64
import jinja2
import string

from pathlib import Path


class Font(msgspec.Struct):
    name: str
    filename: str  # path relative to Path("./fonts")
    symbols: str  # path relative to Path("./fonts")
    extra: list[int] = msgspec.field(default_factory=list)


class TargetFont(msgspec.Struct):
    filename: str
    source: str


class Config(msgspec.Struct):
    private_range: tuple[int, int]
    fonts: dict[str, Font]
    targets: dict[str, TargetFont]


class ReplacementMap(msgspec.Struct):
    # font -> symbol -> replacement
    replacements: dict[str, dict[str, str]]


def make_replacement_map(
    fonts: dict[str, Font],
    default_font: str | None = None,
    private_range: tuple[int, int] = (0xE000, 0xF8FF),
) -> ReplacementMap:
    replacements = {}

    # Private range (E000-F8FF)
    current_symbol = private_range[0]
    for font_name, font in fonts.items():
        replacements[font_name] = {}
        symbols_path = Path("fonts") / font.symbols
        content = symbols_path.read_text()
        content = list("".join(line.strip() for line in content.split("\n")))
        content.extend(chr(codepoint) for codepoint in font.extra)

        for symbol in content:
            if symbol in replacements[font_name]:
                continue

            if font_name == default_font:
                replacements[font_name][symbol] = symbol
                continue

            replacements[font_name][symbol] = chr(current_symbol)
            current_symbol += 1
            if current_symbol >= private_range[1]:
                raise ValueError("Private range is full, use different range")

    return ReplacementMap(replacements=replacements)


def wrap_lines(content: str, line_length: int = 20) -> list[str]:
    return [content[i : i + line_length] for i in range(0, len(content), line_length)]


def merge_fonts(
    base_font: Path,
    output_path: Path,
    fonts: dict[str, Font],
    replacement_map: ReplacementMap,
) -> Path:
    merged_font = fontforge.open(str(base_font))
    merged_font.encoding = "UnicodeFull"

    fonts_dir = Path("fonts")

    for font_name, symbol_map in replacement_map.replacements.items():
        source_font_info = fonts[font_name]
        source_font_path = fonts_dir / source_font_info.filename

        print(f"Processing font: {font_name} from {source_font_path}")
        source_font = fontforge.open(str(source_font_path))

        for glyph_name in source_font:
            glyph = source_font[glyph_name]
            glyph.unlinkRef()

        for original_symbol, replacement_char in symbol_map.items():
            original_codepoint = ord(original_symbol)
            replacement_codepoint = ord(replacement_char)

            source_font.selection.select(original_codepoint)
            source_font.copy()
            merged_font.selection.select(replacement_codepoint)
            merged_font.paste()
            merged_font[
                replacement_codepoint
            ].glyphname = f"uni{replacement_codepoint:04X}_from_{font_name}"

        # source_font.close()

    print(f"Generating merged font at: {output_path}")
    merged_font.generate(str(output_path))
    merged_font.close()

    return output_path


def main():
    with open("config.toml", "rb") as f:
        data = msgspec.toml.decode(f.read(), type=Config)

    replacement_map = make_replacement_map(
        data.fonts, private_range=data.private_range
    )
    print("Replacement Map created.")

    output_dir = Path("./dist")
    output_dir.mkdir(parents=True, exist_ok=True)

    for target_font in data.targets.values():
        merge_fonts(
            Path("fonts") / target_font.source,
            output_dir / target_font.filename,
            data.fonts,
            replacement_map,
        )

    with open(output_dir / "replacement_map.json", "w") as f:
        json.dump(replacement_map.replacements, f, indent=2)

    fallback_font_path = Path("./fallback_font.ttf")
    fallback_font_content = fallback_font_path.read_bytes()
    checksum = {}

    with open("preview.jinja", "r") as f:
        template = jinja2.Template(f.read())

    for target_name, target_font in data.targets.items():
        font_path = output_dir / target_font.filename
        md5_hash = hashlib.md5()

        with font_path.open("rb") as font_file:
            font_content = font_file.read()
            md5_hash.update(font_content)

        checksum[target_name] = md5_hash.hexdigest()

        preview_text = {
            font_name: wrap_lines("".join(font_replacements.values()), 64)
            for font_name, font_replacements in replacement_map.replacements.items()
        }

        preview_text["base"] = wrap_lines(
            string.ascii_letters + string.digits + string.punctuation, 64
        )

        preview = template.render(
            font_name=target_name,
            font_data=base64.b64encode(font_content).decode("utf-8"),
            fallback_font=base64.b64encode(fallback_font_content).decode("utf-8"),
            preview_text=preview_text,
        )

        with open(output_dir / f"preview_{target_name}.html", "w") as f:
            f.write(preview)

    checksum_path = output_dir / "checksum.json"
    with open(checksum_path, "w") as checksum_file:
        json.dump(checksum, checksum_file, indent=2)

    print(f"MD5 checksums saved to: {checksum_path}")

    print("Done.")


if __name__ == "__main__":
    main()
