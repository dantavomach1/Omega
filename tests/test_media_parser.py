from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from omega.library.media_parser import clean_media_title, parse_media_path


def test_movie_title_year_and_release_noise_are_parsed():
    parsed = parse_media_path(Path("Movies") / "The.Matrix.1999.1080p.BluRay.x265-GRP.mkv")

    assert parsed.media_type == "movie"
    assert parsed.cleaned_title == "The Matrix"
    assert parsed.year == 1999
    assert parsed.confidence >= 0.75


def test_show_episode_from_season_folder_is_groupable():
    parsed = parse_media_path(Path("Shows") / "Fringe" / "Season 02" / "Fringe.S02E03.Fracture.1080p.WEB-DL.mkv")

    assert parsed.media_type == "episode"
    assert parsed.cleaned_title == "Fringe"
    assert parsed.season == 2
    assert parsed.episode == 3


def test_title_cleanup_strips_common_codec_audio_and_source_tags():
    assert clean_media_title("Some_Show_1x02_WEBRip_HEVC_AAC-[ReleaseGroup]") == "Some Show 1x02"
