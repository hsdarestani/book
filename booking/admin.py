from django.contrib import admin
from .models import Appointment, BlockedPeriod, Customer, Service, StaffMember, WorkingHour


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
    list_display = ('last_name', 'first_name', 'email', 'phone', 'created_at')
    search_fields = ('first_name', 'last_name', 'email', 'phone')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('starts_at', 'customer', 'service', 'staff', 'status', 'source')
    list_filter = ('status', 'source', 'service', 'staff')
    search_fields = ('customer__first_name', 'customer__last_name', 'customer__email', 'customer__phone')
    date_hierarchy = 'starts_at'
    readonly_fields = ('public_id', 'idempotency_key', 'created_at', 'updated_at')
    autocomplete_fields = ('customer',)
