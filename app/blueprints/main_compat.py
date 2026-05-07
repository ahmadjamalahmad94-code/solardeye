from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════
# LEGACY URL BRIDGE — main_compat.py
# ═══════════════════════════════════════════════════════════════════════
# This module exists to keep `url_for('main.<name>')` calls working in
# templates while the actual route handlers have moved to dedicated
# blueprints (users_routes, energy, support, notifications_routes, etc.).
#
# Each function below is a thin stub registered under the 'main' blueprint
# that simply delegates to the real implementation in its proper blueprint.
#
# DEPRECATION PATH (low priority, high risk — defer):
#   For each stub, the long-term cleanup is to:
#     1. Update every `url_for('main.X')` in templates to use the proper
#        blueprint endpoint, e.g. `url_for('users_routes.admin_user_profile')`.
#     2. Test every page to confirm no broken links.
#     3. Remove the stub.
#
# This is currently 62 stubs × multiple template references each → ~200
# call-site updates with full regression testing required. Until then,
# the bridge stays.
#
# Updated: 2026-05-05  (added structural docs)
# ═══════════════════════════════════════════════════════════════════════


def register_main_compat_routes(main_bp):
    @main_bp.route('/admin/users/<int:user_id>', methods=['GET', 'POST'])
    def admin_user_profile(*args, **kwargs):
        from .users_routes import admin_user_profile as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/admin/users', methods=['GET', 'POST'])
    def admin_users(*args, **kwargs):
        from .users_routes import admin_users as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/admin/users/legacy', methods=['GET', 'POST'])
    def admin_users_legacy(*args, **kwargs):
        from .users_routes import admin_users_legacy as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/admin/users/new', methods=['GET', 'POST'])
    def admin_user_create(*args, **kwargs):
        from .users_routes import admin_user_create as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/admin/users/<int:user_id>/toggle', methods=['POST'])
    def admin_user_toggle(*args, **kwargs):
        from .users_routes import admin_user_toggle as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/admin/users/<int:user_id>/delete', methods=['POST'])
    def admin_user_delete(*args, **kwargs):
        from .users_routes import admin_user_delete as _impl
        return _impl(*args, **kwargs)

    # --- Heavy v10.1 compatibility route stubs ---
    @main_bp.route('/')
    def index(*args, **kwargs):
        from .energy import index as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/admin/dashboard')
    def admin_dashboard(*args, **kwargs):
        from .energy import admin_dashboard as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/dashboard')
    def dashboard(*args, **kwargs):
        from .energy import dashboard as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/api/live')
    def api_live(*args, **kwargs):
        from .energy import api_live as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/statistics')
    def statistics(*args, **kwargs):
        from .energy import statistics as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/reports')
    def reports(*args, **kwargs):
        from .energy import reports as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/statistics/export/csv')
    def export_statistics_csv(*args, **kwargs):
        from .energy import export_statistics_csv as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/statistics/export/pdf')
    def export_statistics_pdf(*args, **kwargs):
        from .energy import export_statistics_pdf as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/deye', methods=['GET', 'POST'])
    def deye_settings(*args, **kwargs):
        from .energy import deye_settings as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/test-connection', methods=['POST'])
    def test_connection(*args, **kwargs):
        from .energy import test_connection as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/sync-now', methods=['POST'])
    def sync_now(*args, **kwargs):
        from .energy import sync_now as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/diagnostics')
    def diagnostics(*args, **kwargs):
        from .energy import diagnostics as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/live-data')
    def live_data(*args, **kwargs):
        from .energy import live_data as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/devices/select/<int:device_id>', methods=['POST'])
    def select_device(*args, **kwargs):
        from .devices_routes import select_device as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/devices/manage', methods=['GET', 'POST'])
    def devices_manage(*args, **kwargs):
        from .devices_routes import devices_manage as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/account/profile', methods=['GET', 'POST'])
    def account_profile(*args, **kwargs):
        from .devices_routes import account_profile as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/devices/manage/<int:device_id>/edit', methods=['GET', 'POST'])
    def device_edit(*args, **kwargs):
        from .devices_routes import device_edit as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/devices/manage/<int:device_id>/toggle', methods=['POST'])
    def device_toggle(*args, **kwargs):
        from .devices_routes import device_toggle as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/onboarding', methods=['GET', 'POST'])
    def onboarding_wizard(*args, **kwargs):
        from .devices_routes import onboarding_wizard as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/onboarding/skip', methods=['POST'])
    def onboarding_skip(*args, **kwargs):
        from .devices_routes import onboarding_skip as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/admin/system-logs')
    def admin_system_logs(*args, **kwargs):
        from .users_routes import admin_system_logs as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/devices')
    def devices(*args, **kwargs):
        from .devices_routes import devices as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/battery-lab')
    def battery_lab(*args, **kwargs):
        from .devices_routes import battery_lab as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/loads', methods=['GET', 'POST'])
    def loads_page(*args, **kwargs):
        from .energy import loads_page as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/alerts')
    def alerts(*args, **kwargs):
        from .notifications_routes import alerts as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/notifications/action', methods=['POST'])
    def notifications_action(*args, **kwargs):
        from .notifications_routes import notifications_action as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/channels', methods=['GET', 'POST'])
    def channels(*args, **kwargs):
        from .notifications_routes import channels as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/notifications', methods=['GET', 'POST'])
    def notifications_settings(*args, **kwargs):
        from .notifications_routes import notifications_settings as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/notifications/test', methods=['POST'])
    def notifications_test_send(*args, **kwargs):
        from .notifications_routes import notifications_test_send as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/notifications/test-section', methods=['POST'])
    def notifications_test_section(*args, **kwargs):
        from .notifications_routes import notifications_test_section as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/telegram/menu/send', methods=['POST'])
    def telegram_send_menu_route(*args, **kwargs):
        from .notifications_routes import telegram_send_menu_route as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/telegram/webhook', methods=['GET', 'POST'], strict_slashes=False)
    def telegram_webhook(*args, **kwargs):
        from .notifications_routes import telegram_webhook as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/plant-info')
    def plant_info(*args, **kwargs):
        from .energy import plant_info as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/api/raw-debug')
    def api_raw_debug(*args, **kwargs):
        from .energy import api_raw_debug as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/admin/plans')
    def admin_plans(*args, **kwargs):
        from .billing import admin_plans as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/admin/plans/new', methods=['GET','POST'])
    def admin_plan_create(*args, **kwargs):
        from .billing import admin_plan_create as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/admin/plans/<int:plan_id>/edit', methods=['GET','POST'])
    def admin_plan_edit(*args, **kwargs):
        from .billing import admin_plan_edit as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/admin/subscribers')
    def admin_subscribers(*args, **kwargs):
        from .billing import admin_subscribers as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/admin/subscribers/<int:user_id>/activate', methods=['GET','POST'])
    def admin_subscriber_activate(*args, **kwargs):
        from .billing import admin_subscriber_activate as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/account/subscription')
    def account_subscription(*args, **kwargs):
        from .billing import account_subscription as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/admin/subscriptions')
    def admin_subscriptions(*args, **kwargs):
        from .billing import admin_subscriptions as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/admin/mail', methods=['GET', 'POST'])
    def admin_internal_mail(*args, **kwargs):
        from .support import admin_internal_mail as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/admin/finance', methods=['GET', 'POST'])
    def admin_finance(*args, **kwargs):
        from .billing import admin_finance as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/admin/activity-log')
    def admin_activity_log(*args, **kwargs):
        from .users_routes import admin_activity_log as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/admin/roles')
    def admin_roles(*args, **kwargs):
        from .users_routes import admin_roles as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/admin/tickets', methods=['GET', 'POST'])
    def admin_tickets(*args, **kwargs):
        from .support import admin_tickets as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/admin/quotas', methods=['GET', 'POST'])
    def admin_quotas(*args, **kwargs):
        from .billing import admin_quotas as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/support', methods=['GET', 'POST'])
    @main_bp.route('/portal/support', methods=['GET', 'POST'])
    def portal_support(*args, **kwargs):
        from .support import portal_support as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/portal/messages', methods=['GET', 'POST'])
    def portal_messages(*args, **kwargs):
        from .support import portal_messages as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/portal/tickets', methods=['GET', 'POST'])
    def portal_tickets(*args, **kwargs):
        from .support import portal_tickets as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/notifications/feed')
    def notifications_feed(*args, **kwargs):
        from .notifications_routes import notifications_feed as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/notification-center')
    @main_bp.route('/notifications/center')
    def notification_center(*args, **kwargs):
        from .notifications_routes import notification_center as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/admin/support-command-center')
    def admin_support_command_center(*args, **kwargs):
        from .support import admin_support_command_center as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/admin/support-command-center/action', methods=['POST'])
    def admin_support_command_action(*args, **kwargs):
        from .support import admin_support_command_action as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/admin/support-command-center/reopen', methods=['POST'])
    def admin_support_reopen(*args, **kwargs):
        from .support import admin_support_reopen as _impl
        return _impl(*args, **kwargs)

    @main_bp.route('/notifications/mark-read', methods=['POST'])
    def notifications_mark_read(*args, **kwargs):
        from .notifications_routes import notifications_mark_read as _impl
        return _impl(*args, **kwargs)
