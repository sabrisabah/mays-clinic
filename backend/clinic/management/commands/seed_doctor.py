from django.core.management.base import BaseCommand
from clinic.models import User

DOCTOR_EMAIL = "doctor@mays.clinic"
DOCTOR_PASSWORD = "doctor123"


class Command(BaseCommand):
    help = "Creates a default doctor account (doctor@mays.clinic / doctor123) so you can log in immediately."

    def handle(self, *args, **options):
        if User.objects.filter(email=DOCTOR_EMAIL).exists():
            self.stdout.write(self.style.WARNING(f"Doctor account already exists: {DOCTOR_EMAIL}"))
            return

        User.objects.create_user(
            email=DOCTOR_EMAIL,
            password=DOCTOR_PASSWORD,
            full_name="د. مسؤول العيادة",
            role="doctor",
            is_staff=True,  # can also log into /admin to create more doctor accounts
        )
        self.stdout.write(self.style.SUCCESS("Doctor account created:"))
        self.stdout.write(f"  email:    {DOCTOR_EMAIL}")
        self.stdout.write(f"  password: {DOCTOR_PASSWORD}")
