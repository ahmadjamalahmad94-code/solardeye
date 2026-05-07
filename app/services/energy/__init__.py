"""Energy subsystem service helpers.

This package is the target destination for chart-building and export logic
currently inline inside `app/blueprints/energy.py` route handlers. The
blueprint should eventually depend on functions in this package rather
than holding all logic inline.

Recommended decomposition (future work):
    chart_data.py     — build_dashboard_chart_payload(),
                        build_battery_chart_payload(),
                        build_stats_profile_payload()
    csv_export.py     — render_statistics_csv(rows, lang)
    pdf_export.py     — render_statistics_pdf(rows, lang)
    live_metrics.py   — compute_live_snapshot(reading, settings)
    deye_sync.py      — run_deye_test(), trigger_sync()

Status: scaffold only — actual extraction requires per-route surgery
since current handlers contain inline business logic up to ~770 lines.
"""
