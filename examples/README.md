# Synthetic demo data

This folder contains **fully synthetic data created only for demonstration**. None of the records come from field observations or research participants.

## Files

- `synthetic_data/sensor_A.csv` – fictional raw detections for BLE sensor A.
- `synthetic_data/sensor_B.csv` – fictional raw detections for BLE sensor B.
- `expected_output/events_with_device.csv` – output produced by the BLE processing pipeline.
- `expected_output/device_visits.csv` – reconstructed synthetic visits.
- `expected_output/device_visits_dwell_positive.csv` – visits with positive overlap/dwell time.

The fictional MAC addresses, device metadata, timestamps, and RSSI values were generated specifically for this repository.

## Demo scenarios

The example contains five fictional visits with both A→B and B→A temporal patterns and different overlap durations. It is intentionally small so the processing steps can be inspected manually.
