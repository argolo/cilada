"""A test module containing pytest functions to validate various aspects of.

Configuration loading, including method handling, type validation, HTTP status code
counting, and TOML/URL parsing.

"""

from pathlib import Path

import pytest

from cilada.config import ConfigurationError, load_settings, should_mark_failure


def test_loads_methods_in_uppercase(tmp_path: Path) -> None:
    """Tests that the loaded configuration converts method names to uppercase.

    Args:
        tmp_path: A temporary path object used for creating a mock configuration file.

    """
    config = tmp_path / ".cilada.toml"
    config.write_text('[test]\nenabled_methods = ["get", "post"]\n', encoding="utf-8")

    settings = load_settings(config)

    assert settings.test.enabled_methods == ["GET", "POST"]


def test_rejects_invalid_method(tmp_path: Path) -> None:
    """Tests that loading settings fails with a ConfigurationError when an invalid.

    Method is specified in the configuration file.

    Args:
        tmp_path: A temporary path object used for creating and managing test files.

    """
    config = tmp_path / ".cilada.toml"
    config.write_text('[test]\nenabled_methods = ["BREW"]\n', encoding="utf-8")

    with pytest.raises(ConfigurationError, match="BREW"):
        load_settings(config)


@pytest.mark.parametrize(
    ("content", "field"),
    [
        ('[api]\nverify_tls = "false"\n', "api.verify_tls"),
        ('[test]\ninclude_paths = "/patients/*"\n', "test.include_paths"),
        ('[locust]\nusers = "10"\n', "locust.users"),
    ],
)
def test_rejects_invalid_configuration_types(
    tmp_path: Path, content: str, field: str
) -> None:
    """Tests that the settings loading function raises a ConfigurationError when.

    Provided with invalid configuration types.

    Args:
        tmp_path: A temporary path object used for creating and managing test files.
        content: The string content to be written into the configuration file.
        field: The expected error message substring that should be matched by the
        ConfigurationError.

    """
    config = tmp_path / ".cilada.toml"
    config.write_text(content, encoding="utf-8")

    with pytest.raises(ConfigurationError, match=field):
        load_settings(config)


def test_configures_http_status_classes_that_count_as_failures(tmp_path: Path) -> None:
    """Tests that the configuration correctly sets HTTP status classes.

    That should be counted as failures.

    Args:
        tmp_path: A temporary path object used for creating and managing test files.

    """
    config = tmp_path / ".cilada.toml"
    config.write_text("[test]\nfailure_status_classes = [4, 5]\n", encoding="utf-8")

    settings = load_settings(config)

    assert settings.test.failure_status_classes == [4, 5]
    assert should_mark_failure(404, settings.test.failure_status_classes)
    assert should_mark_failure(500, settings.test.failure_status_classes)
    assert not should_mark_failure(201, settings.test.failure_status_classes)


def test_rejects_invalid_toml(tmp_path: Path) -> None:
    """Tests that the settings loading function raises a ConfigurationError when.

    Provided with an invalid TOML file.

    Args:
        tmp_path: A temporary path object used to create and manage test files.

    """
    config = tmp_path / ".cilada.toml"
    config.write_text("[api\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="invalid TOML"):
        load_settings(config)


@pytest.mark.parametrize(
    ("content", "field"),
    [
        ('[api]\nopenapi_url = "not-a-url"\n', "api.openapi_url"),
        ('[locust]\ncsv_prefix = "   "\n', "locust.csv_prefix"),
    ],
)
def test_rejects_invalid_url_and_empty_report_paths(
    tmp_path: Path, content: str, field: str
) -> None:
    """Tests that the settings loading function raises a ConfigurationError when.

    Provided with invalid URLs or empty report paths.

    Args:
        tmp_path: A temporary path object used for creating configuration files during
        testing.
        content: The content string to be written into the configuration file.
        field: The expected error message substring that should be matched by the
        ConfigurationError.

    """
    config = tmp_path / ".cilada.toml"
    config.write_text(content, encoding="utf-8")

    with pytest.raises(ConfigurationError, match=field):
        load_settings(config)
