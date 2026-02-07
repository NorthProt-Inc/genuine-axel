"""Tests for SENSOR_GROUPS data integrity."""

from backend.core.tools.hass_ops import get_sensor_groups


class TestSensorGroupIntegrity:
    """Verify sensor group structure and consistency."""

    def test_printer_ink_all_is_subset_of_printer(self):
        """All printer_ink_all sensors must exist in printer group."""
        groups = get_sensor_groups()
        ink_sensors = set(groups["printer_ink_all"])
        printer_sensors = set(groups["printer"])
        assert ink_sensors.issubset(printer_sensors)

    def test_no_duplicate_entries_in_any_group(self):
        """Each group should have no duplicate entries."""
        for name, sensors in get_sensor_groups().items():
            assert len(sensors) == len(set(sensors)), f"Duplicates in {name}"

    def test_printer_group_has_status_and_page_counter(self):
        """Printer group should include non-ink sensors too."""
        printer = get_sensor_groups()["printer"]
        assert any("status" in s for s in printer)
        assert any("page_counter" in s for s in printer)

    def test_ink_sensors_share_identity(self):
        """printer_ink_all list objects should be the same reference as used in printer."""
        groups = get_sensor_groups()
        ink_all = groups["printer_ink_all"]
        printer = groups["printer"]
        for sensor in ink_all:
            assert sensor in printer
