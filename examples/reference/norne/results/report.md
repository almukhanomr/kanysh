# Kanysh Basic calculation report

Run: `job-b59790ed0fd54038`

Numerical checks: **PASS**. Geological fitness: **REQUIRES REVIEW**.

Initial oil in place; not recoverable reserves or a production forecast

```json
{
  "contacts": [
    {
      "name": "depth-2585.5",
      "contact_z_m": -2585.5,
      "GRV": 3375172339.6501703,
      "GRV_oil_interval": 346429573.2012896,
      "HCPV": 52134491.25374805,
      "NetRockVolume": 274419763.2559867,
      "PV": 69512655.0049974,
      "STOIIP": 43445409.37812338
    },
    {
      "name": "depth-2618.0",
      "contact_z_m": -2618.0,
      "GRV": 3375172339.6501703,
      "GRV_oil_interval": 681214195.8445195,
      "HCPV": 109089992.21517323,
      "NetRockVolume": 572838990.2880124,
      "PV": 145453322.95356432,
      "STOIIP": 90908326.8459777
    },
    {
      "name": "depth-2693.3",
      "contact_z_m": -2693.3,
      "GRV": 3375172339.6501703,
      "GRV_oil_interval": 1667436549.9621353,
      "HCPV": 281891561.05814934,
      "NetRockVolume": 1467873614.6072454,
      "PV": 375855414.7441991,
      "STOIIP": 234909634.21512446
    }
  ],
  "assumptions": [
    "Public OPM Norne field benchmark geometry/ACTNUM/PORO/PERMX/NTG/FIPNUM; pinned source commit",
    "Coordinates metres, Z = negative source depth; CRS/datum not independently established",
    "Explicit benchmark constants Sw=0.25, Kz/Kx=0.1, Bo=1.2; not Norne dynamic initialization",
    "Three uniform OWC sensitivity alternatives selected from full-deck EQUIL inside active geometry; not regional equilibrium",
    "Warped corner-point cells use six tetrahedra along diagonal 0–7",
    "Contact selection: {\"active_depth_range_m\": [2439.10888671875, 3090.133056640625], \"depths_m\": [2585.5, 2618.0, 2693.3], \"evidence\": [{\"file\": \"full/norne/INCLUDE/PETRO/E3.prop\", \"goc_depth_m\": 2500.0, \"line\": 19, \"owc_depth_m\": 2585.5, \"region_id\": 2}, {\"file\": \"full/norne/INCLUDE/PETRO/E3.prop\", \"goc_depth_m\": 2582.0, \"line\": 20, \"owc_depth_m\": 2618.0, \"region_id\": 3}, {\"file\": \"full/norne/INCLUDE/PETRO/E3.prop\", \"goc_depth_m\": 2585.0, \"line\": 22, \"owc_depth_m\": 2693.3, \"region_id\": 5}], \"source\": \"EQUIL OWC records; applied uniformly only as static sensitivity alternatives, not regional equilibrium initialization\"}"
  ],
  "missing": [],
  "failures": []
}
```

See report.html, report.json, volumes.csv and volumes.png for the full evidence.
