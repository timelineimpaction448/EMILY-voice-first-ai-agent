"""Data services for the HUD — system metrics, network, weather, trackers, audio.

Services poll their sources on background threads and expose the latest snapshot
to the UI. Widgets read snapshots (or connect to Qt signals via the hub). All
network calls are keyless, time-limited, cached to disk, and degrade to a visible
offline state.
"""
