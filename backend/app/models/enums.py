from enum import StrEnum


class UserRole(StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"
    AGENT = "AGENT"
    USER = "USER"


class TicketStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class TicketPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
