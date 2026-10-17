# OpenSubsurface calculation report

Run: `job-f25ad48a0e1f4979`

Numerical checks: **PASS**. Geological fitness: **REQUIRES REVIEW**.

Initial oil in place; not recoverable reserves or a production forecast

```json
{
  "contacts": [
    {
      "name": "full_control",
      "contact_z_m": -3709.416,
      "GRV": 12708600.750489552,
      "GRV_oil_interval": 12708600.750489498,
      "HCPV": 1734437.0656560338,
      "NetRockVolume": 12708600.750489498,
      "PV": 2168046.3320700424,
      "STOIIP": 1734437.0656560338
    },
    {
      "name": "fractional_control",
      "contact_z_m": -3683.6604,
      "GRV": 12708600.750489552,
      "GRV_oil_interval": 6391678.612746174,
      "HCPV": 916611.1750709807,
      "NetRockVolume": 6391678.612746174,
      "PV": 1145763.968838726,
      "STOIIP": 916611.1750709807
    },
    {
      "name": "dry_control",
      "contact_z_m": -3657.6000000000004,
      "GRV": 12708600.750489552,
      "GRV_oil_interval": 0.0,
      "HCPV": 0.0,
      "NetRockVolume": 0.0,
      "PV": 0.0,
      "STOIIP": 0.0
    }
  ],
  "assumptions": [
    "Source geometry converted FIELD feet to metres; local X/Y origin0, unspecified source depth datum",
    "All cells active; one zone; explicit NTG=1, Sw=.2, Bo=1 solely for numerical control",
    "Preserve published PORO exactly, including remaining zeros, and original permeability; PERMY checked equal to PERMX"
  ],
  "missing": [],
  "failures": []
}
```

See report.html, report.json, volumes.csv and volumes.png for the full evidence.
