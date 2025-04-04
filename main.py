import msgspec
import fontforge
import json
import hashlib
import base64
import jinja2

from pathlib import Path


class Font(msgspec.Struct):
    name: str
    filename: str  # path relative to Path("./fonts")
    symbols: str  # path relative to Path("./fonts")


class Config(msgspec.Struct):
    merged_font_name: str
    default_font: str
    fonts: dict[str, Font]


class ReplacementMap(msgspec.Struct):
    # font -> symbol -> replacement
    replacements: dict[str, dict[str, str]]


def make_replacement_map(
    fonts: dict[str, Font],
    default_font: str | None = None,
    private_range: tuple[int, int] = (0xE000, 0xF8FF)
) -> ReplacementMap:
    replacements = {}

    # Private range (E000-F8FF)
    current_symbol = private_range[0]
    for font_name, font in fonts.items():
        replacements[font_name] = {}
        symbols_path = Path("fonts") / font.symbols
        content = symbols_path.read_text()
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


def merge_fonts(fonts: dict[str, Font], replacement_map: ReplacementMap, output_path: Path, merged_font_name: str) -> Path:
    merged_font = fontforge.font()
    merged_font.encoding = "UnicodeFull"
    merged_font.fontname = merged_font_name
    merged_font.familyname = merged_font_name
    merged_font.fullname = merged_font_name

    fonts_dir = Path("fonts")

    for font_name, symbol_map in replacement_map.replacements.items():
        source_font_info = fonts[font_name]
        source_font_path = fonts_dir / source_font_info.filename

        print(f"Processing font: {font_name} from {source_font_path}")
        source_font = fontforge.open(str(source_font_path))

        for original_symbol, replacement_char in symbol_map.items():
            original_codepoint = ord(original_symbol)
            replacement_codepoint = ord(replacement_char)

            source_font.selection.select(original_codepoint)
            source_font.copy()
            merged_font.selection.select(replacement_codepoint)
            merged_font.paste()
            merged_font[replacement_codepoint].glyphname = f"uni{replacement_codepoint:04X}_from_{font_name}"

        source_font.close()

    print(f"Generating merged font at: {output_path}")
    merged_font.generate(str(output_path))
    merged_font.close()

    return output_path


def main():
    with open("config.toml", "rb") as f:
        data = msgspec.toml.decode(f.read(), type=Config)

    replacement_map = make_replacement_map(data.fonts, data.default_font)
    print("Replacement Map created.")

    output_dir = Path("./dist")
    output_dir.mkdir(parents=True, exist_ok=True)
    merge_fonts(data.fonts, replacement_map, output_dir / "merged_font.ttf", data.merged_font_name)

    with open(output_dir / "replacement_map.json", "w") as f:
        json.dump(replacement_map.replacements, f, indent=2)
    
    font_path = output_dir / "merged_font.ttf"
    md5_hash = hashlib.md5()
    
    with open(font_path, "rb") as font_file:
        font_content = font_file.read()
        md5_hash.update(font_content)
    
    checksum_path = output_dir / "checksum.txt"
    with open(checksum_path, "w") as checksum_file:
        checksum_file.write(md5_hash.hexdigest())

    print(f"MD5 checksum saved to: {checksum_path}")

    with open("preview.jinja", "r") as f:
        template = jinja2.Template(f.read())

    preview = template.render(
        font_name=data.merged_font_name,
        font_data=base64.b64encode(font_content).decode("utf-8"),
        preview_text={
            font_name: "".join(font_replacements.values())
            for font_name, font_replacements in replacement_map.replacements.items()
        }
    )

    with open(output_dir / "preview.html", "w") as f:
        f.write(preview)

    print("Done.")


if __name__ == "__main__":
    main()
