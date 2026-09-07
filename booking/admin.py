from django.contrib import admin
from .models import (
    AdminAccessProfile,
    Appointment,
    BlockedPeriod,
    Customer,
    Service,
    StaffMember,
    WhatsAppTemplate,
    WorkingHour,
)


class WorkingHourInline(admin.TabularInline):
    model = WorkingHour
    extra = 1


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'duration_minutes', 'price_label', 'active', 'bookable', 'requires_confirmation')
    list_filter = ('active', 'bookable', 'requires_confirmation')
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}
    ordering = ('sort_order', 'name')


@admin.register(StaffMember)
class StaffMemberAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'role', 'active')
    list_filter = ('role', 'active')
    search_fields = ('display_name', 'bio')
    filter_horizontal = ('services',)
    inlines = [WorkingHourInline]


@admin.register(WorkingHour)
class WorkingHourAdmin(admin.ModelAdmin):
    list_display = ('staff', 'weekday', 'start_time', 'end_time', 'active')
    list_filter = ('weekday', 'active')


@admin.register(BlockedPeriod)
class BlockedPeriodAdmin(admin.ModelAdmin):
    list_display = ('staff', 'starts_at', 'ends_at', 'reason')
    list_filter = ('staff',)
    search_fields = ('reason', 'staff__display_name')


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('last_name', 'first_name', 'salutation', 'email', 'phone', 'created_at')
    list_filter = ('salutation',)
    search_fields = ('first_name', 'last_name', 'email', 'phone')
    ordering = ('last_name', 'first_name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('starts_at', 'customer', 'service', 'staff', 'status', 'source')
    list_filter = ('status', 'source', 'service', 'staff')
    search_fields = ('customer__first_name', 'customer__last_name', 'customer__email', 'customer__phone')
    date_hierarchy = 'starts_at'
    readonly_fields = ('public_id', 'idempotency_key', 'created_at', 'updated_at')
    autocomplete_fields = ('customer',)


@admin.register(AdminAccessProfile)
class AdminAccessProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'staff', 'view_only', 'updated_at')
    list_filter = ('view_only', 'staff')
    search_fields = ('user__username', 'user__email', 'user__first_name', 'user__last_name', 'staff__display_name')
    autocomplete_fields = ('user',)


@admin.register(WhatsAppTemplate)
class WhatsAppTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'active', 'sort_order', 'updated_at')
    list_filter = ('active',)
    search_fields = ('name', 'body')
    ordering = ('sort_order', 'name')
