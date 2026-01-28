import unittest
from unittest.mock import patch, MagicMock
from src.utils.conflict_detector import check_scheduler_conflict

class TestConflictDetector(unittest.TestCase):

    @patch('src.utils.conflict_detector.get_calendar_service')
    def test_conflict_exists(self, mock_get_service):
        """
        Scenario: The API returns a list of events (User is BUSY).
        Expected: Returns True
        """
        # 1. Setup the Mock
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        
        # Simulate API response with one existing meeting
        mock_events_result = {
            'items': [
                {'summary': 'Existing Meeting', 'start': {'dateTime': '2025-01-27T15:00:00Z'}}
            ]
        }
        
        # Chain the mock calls: service.events().list().execute()
        mock_service.events.return_value.list.return_value.execute.return_value = mock_events_result

        # 2. Call the function
        result = check_scheduler_conflict(
            scheduler_email="test@example.com",
            start_datetime="2025-01-27T15:00:00",
            end_datetime="2025-01-27T16:00:00"
        )

        # 3. Assertions
        self.assertTrue(result, "Should return True when events are found")
        
        # Verify arguments passed to API (Section 3.5 Integration Protocol)
        mock_service.events.return_value.list.assert_called_with(
            calendarId='primary',
            timeMin="2025-01-27T15:00:00Z", # Our code appends 'Z'
            timeMax="2025-01-27T16:00:00Z",
            singleEvents=True,
            orderBy='startTime'
        )

    @patch('src.utils.conflict_detector.get_calendar_service')
    def test_no_conflict_found(self, mock_get_service):
        """
        Scenario: The API returns an empty list (User is FREE).
        Expected: Returns False
        """
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        
        # Simulate empty response
        mock_events_result = {'items': []}
        mock_service.events.return_value.list.return_value.execute.return_value = mock_events_result

        result = check_scheduler_conflict(
            scheduler_email="test@example.com",
            start_datetime="2025-01-28T10:00:00",
            end_datetime="2025-01-28T11:00:00"
        )

        self.assertFalse(result, "Should return False when no events are found")

    @patch('src.utils.conflict_detector.get_calendar_service')
    def test_api_failure_failsafe(self, mock_get_service):
        """
        Scenario: Google API raises an exception (e.g., Network Error).
        Expected: Returns True (Fail-safe: assume busy to prevent double booking)
        """
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        
        # Simulate an API error
        mock_service.events.return_value.list.side_effect = Exception("API Connection Failed")

        result = check_scheduler_conflict(
            scheduler_email="test@example.com",
            start_datetime="2025-01-29T10:00:00",
            end_datetime="2025-01-29T11:00:00"
        )

        self.assertTrue(result, "Should return True (fail-safe) on API exception")

if __name__ == '__main__':
    unittest.main()