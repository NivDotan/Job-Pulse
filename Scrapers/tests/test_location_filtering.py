from telegramInsertBot import is_location_in_israel, is_location_in_israel_or_usa


def test_israeli_cities_return_true():
    assert is_location_in_israel("Tel Aviv") is True
    assert is_location_in_israel("Jerusalem") is True
    assert is_location_in_israel("Haifa") is True


def test_blacklisted_city_returns_false():
    assert is_location_in_israel("chicago") is False
    assert is_location_in_israel("Nashville") is False


def test_israel_keyword_in_location_string_returns_true():
    assert is_location_in_israel("New York, Israel") is True
    assert is_location_in_israel("Remote (Israel)") is True


def test_israel_or_usa_filter_allows_us_locations():
    assert is_location_in_israel_or_usa("US, California, Santa Clara") is True
    assert is_location_in_israel_or_usa("USA - Sunnyvale, CA") is True
    assert is_location_in_israel_or_usa("Chicago") is True


def test_israel_or_usa_filter_rejects_other_countries():
    assert is_location_in_israel_or_usa("India, Bengaluru") is False
    assert is_location_in_israel_or_usa("Germany, Berlin") is False
