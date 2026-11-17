"""Role names used by each tenant membership's staff access assignment."""

STAFF_ROLE_NAMES = (
    'Super Admin', 'Admin', 'Content Manager', 'Content Writer', 'Trip Manager', 'Trip Organizer',
    'Booking Manager', 'Finance Manager', 'Customer Support', 'Marketing Manager', 'Operations Manager',
    'Analytics Viewer',
)
STAFF_ROLE_CHOICES = tuple((name, name) for name in STAFF_ROLE_NAMES)
