from django.urls import path

from . import views as v

urlpatterns = [
    path("", v.dashboard, name="dashboard"),
    path("healthz/", v.healthz, name="healthz"),
    # Papers
    path("papers/", v.paper_list, name="paper_list"),
    path("papers/board/", v.paper_board, name="paper_board"),
    path("papers/new/", v.paper_create, name="paper_create"),
    path("papers/<int:pk>/", v.paper_detail, name="paper_detail"),
    path("papers/<int:pk>/edit/", v.paper_edit, name="paper_edit"),
    path("papers/<int:pk>/status/", v.paper_status, name="paper_status"),
    path("papers/<int:pk>/delete/", v.paper_delete, name="paper_delete"),
    # Authors
    path("papers/<int:pk>/authors/add/", v.author_form, name="author_add"),
    path("papers/<int:pk>/authors/<int:author_pk>/", v.author_form, name="author_edit"),
    path("papers/<int:pk>/authors/<int:author_pk>/delete/", v.author_delete, name="author_delete"),
    path("papers/<int:pk>/authors/<int:author_pk>/request/", v.author_request_data, name="author_request"),
    path("author/<str:token>/", v.author_self_update, name="author_self_update"),
    # Submissions & reviews
    path("papers/<int:pk>/submissions/add/", v.submission_form, name="submission_add"),
    path("papers/<int:pk>/submissions/<int:sub_pk>/", v.submission_form, name="submission_edit"),
    path("papers/<int:pk>/submissions/<int:sub_pk>/comments/add/", v.comment_form, name="comment_add"),
    path("papers/<int:pk>/submissions/<int:sub_pk>/comments/import/", v.comment_bulk, name="comment_bulk"),
    path("papers/<int:pk>/submissions/<int:sub_pk>/comments/<int:c_pk>/", v.comment_form, name="comment_edit"),
    path("papers/<int:pk>/submissions/<int:sub_pk>/response-letter/", v.response_letter, name="response_letter"),
    # Deadlines
    path("deadlines/", v.deadline_list, name="deadline_list"),
    path("papers/<int:pk>/deadlines/add/", v.deadline_form, name="deadline_add"),
    path("papers/<int:pk>/deadlines/<int:dl_pk>/", v.deadline_form, name="deadline_edit"),
    path("papers/<int:pk>/deadlines/<int:dl_pk>/toggle/", v.deadline_toggle, name="deadline_toggle"),
    path("papers/<int:pk>/deadlines/<int:dl_pk>/delete/", v.deadline_delete, name="deadline_delete"),
    # Files
    path("papers/<int:pk>/files/add/", v.attachment_add, name="attachment_add"),
    path("papers/<int:pk>/files/<int:att_pk>/", v.attachment_download, name="attachment_download"),
    path("papers/<int:pk>/files/<int:att_pk>/delete/", v.attachment_delete, name="attachment_delete"),
    # Groups
    path("groups/", v.group_list, name="group_list"),
    path("groups/new/", v.group_create, name="group_create"),
    path("groups/<int:pk>/", v.group_detail, name="group_detail"),
    path("groups/<int:pk>/edit/", v.group_edit, name="group_edit"),
    path("groups/<int:pk>/invite/", v.group_invite, name="group_invite"),
    path("groups/<int:pk>/invitations/<int:inv_pk>/revoke/", v.invitation_revoke, name="invitation_revoke"),
    path("groups/<int:pk>/members/<int:mem_pk>/", v.member_update, name="member_update"),
    path("invite/<str:token>/", v.invitation_accept, name="invitation_accept"),
    # Journals
    path("journals/", v.journal_list, name="journal_list"),
    path("journals/new/", v.journal_form, name="journal_create"),
    path("journals/<int:pk>/", v.journal_detail, name="journal_detail"),
    path("journals/<int:pk>/edit/", v.journal_form, name="journal_edit"),
    # Reports & integrations
    path("reports/", v.reports, name="reports"),
    path("export.csv", v.export_csv, name="export_csv"),
    path("calendar/<str:token>.ics", v.calendar_feed, name="calendar_feed"),
    path("cron/<str:job>/", v.cron, name="cron"),
]
