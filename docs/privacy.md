# GoreeCloud Home Privacy Model

Local-only Home operation is a first-class target configuration. Basic local control and future local automation must not require remote telemetry.

High-sensitivity smart-home information includes presence/occupancy, camera/video, audio, access events, lock/door state, behavioral routines, household membership and fine-grained history. Future collection and retention require explicit purpose, user control and Privacy Shield policy enforcement.

The product direction excludes advertising and third-party behavioral analytics as reasons to collect household data.

Current version 0.1.0-dev.1 stores only the domain data explicitly created through internal Home Core methods and the corresponding local SQLite event journal. No cloud telemetry pipeline is implemented.

Privacy Shield runtime integration and application acceptance remain blocked future work.