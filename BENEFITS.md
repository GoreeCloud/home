# GoreeCloud Home — Benefits

This document records intended and currently supportable product value without treating planned capabilities as implemented.

## Current foundation benefits

- Establishes an original GoreeCloud-owned smart-home domain instead of inheriting another product's entity model.
- Separates desired device state from reported reality, which is necessary for honest offline/failure handling.
- Uses a durable local journal so Home state evolution does not depend on a cloud event service.
- Starts with a loopback-only read-only network surface, reducing premature remote-control exposure.
- Keeps runtime dependencies minimal while the architecture is still being established.

## Target product benefits

- Local household control that continues during Internet or GoreeCloud cloud outages.
- One protocol-neutral experience across Matter, Thread, Zigbee, Z-Wave, MQTT, BLE and local LAN devices.
- Advanced automations without requiring users to abandon a simple everyday Home interface.
- Private-by-default handling of presence, camera and household history.
- Recoverable and exportable smart-home configuration instead of ecosystem lock-in.
- GoreeCloud-native Identity, security, privacy, continuity and cross-product coordination.
- Replaceable adapters and clients so protocol or vendor changes do not force a product rewrite.

These target benefits remain objectives until implementation and validation evidence exists.