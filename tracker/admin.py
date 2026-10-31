from django.contrib import admin

from . import models as m


class MembershipInline(admin.TabularInline):
    model = m.GroupMembership
    extra = 0


@admin.register(m.ResearchGroup)
class ResearchGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "institution", "created_at")
    inlines = [MembershipInline]


class AuthorInline(admin.TabularInline):
    model = m.PaperAuthor
    extra = 0


class SubmissionInline(admin.StackedInline):
    model = m.Submission
    extra = 0


class DeadlineInline(admin.TabularInline):
    model = m.Deadline
    extra = 0
    filter_horizontal = ("assignees",)


@admin.register(m.Paper)
class PaperAdmin(admin.ModelAdmin):
    list_display = ("label", "group", "type", "status", "lead", "updated_at")
    list_filter = ("status", "type", "group")
    search_fields = ("title", "short_title", "keywords", "doi")
    inlines = [AuthorInline, SubmissionInline, DeadlineInline]


@admin.register(m.Journal)
class JournalAdmin(admin.ModelAdmin):
    list_display = ("name", "publisher", "kind", "quartile", "indexed_scopus", "indexed_wos", "flagged")
    list_filter = ("kind", "quartile", "indexed_scopus", "indexed_wos", "flagged", "publisher")
    search_fields = ("name", "publisher", "issn", "eissn")


@admin.register(m.Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("paper", "journal", "manuscript_id", "decision", "submitted_at", "revision_due_at")
    list_filter = ("decision",)


@admin.register(m.Deadline)
class DeadlineAdmin(admin.ModelAdmin):
    list_display = ("title", "paper", "kind", "due_at", "completed_at")
    list_filter = ("kind",)


admin.site.register(m.Invitation)
admin.site.register(m.ReviewComment)
admin.site.register(m.Attachment)
admin.site.register(m.ReminderLog)
admin.site.register(m.Activity)
admin.site.site_header = "Research Tracker"
