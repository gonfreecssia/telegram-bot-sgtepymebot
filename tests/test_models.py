"""Tests para modelos de datos."""
from datetime import datetime, timezone, timedelta
import pytest


class TestContainerDetail:
    """Tests para ContainerDetail."""
    
    def test_uptime_calculation(self):
        from app.models import ContainerDetail
        
        now = datetime.now(timezone.utc)
        started = (now - timedelta(hours=3, minutes=45)).isoformat()
        
        cd = ContainerDetail(
            id="test123",
            name="test",
            image="test:latest",
            state="running",
            started_at=started,
        )
        assert cd.uptime_str == "3h 45m"
    
    def test_uptime_days(self):
        from app.models import ContainerDetail
        
        now = datetime.now(timezone.utc)
        started = (now - timedelta(days=2, hours=5)).isoformat()
        
        cd = ContainerDetail(
            id="test123",
            name="test",
            image="test:latest",
            state="running",
            started_at=started,
        )
        assert "2d" in cd.uptime_str
        assert "5h" in cd.uptime_str
    
    def test_uptime_not_running(self):
        from app.models import ContainerDetail
        
        cd = ContainerDetail(
            id="test123",
            name="test",
            image="test:latest",
            state="exited",
            started_at="2024-01-01T00:00:00Z",
        )
        assert cd.uptime_str == "N/A"
    
    def test_memory_str_with_limit(self):
        from app.models import ContainerDetail
        
        cd = ContainerDetail(
            id="test",
            name="test",
            image="test",
            state="running",
            memory_limit=1024 * 1024 * 512,  # 512MB
        )
        assert cd.memory_str == "512MB"
    
    def test_memory_str_no_limit(self):
        from app.models import ContainerDetail
        
        cd = ContainerDetail(id="test", name="test", image="test", state="running")
        assert cd.memory_str == "sin límite"
    
    def test_safe_env_count_filters_password(self):
        from app.models import ContainerDetail
        
        cd = ContainerDetail(
            id="test",
            name="test",
            image="test",
            state="running",
            env_vars=[
                "DB_HOST=localhost",
                "DB_PASSWORD=secret",  # Should be filtered
                "API_KEY=abc123",        # Should be filtered (API_KEY)
                "NODE_ENV=production",
            ],
        )
        # Only DB_HOST and NODE_ENV should be counted (no PASSWORD, no API_KEY)
        assert cd.safe_env_count() == 2


class TestContainerSummary:
    """Tests para ContainerSummary."""
    
    def test_emoji_running(self):
        from app.models import ContainerSummary
        cs = ContainerSummary(
            id="x" * 64,
            name="test",
            image="test:latest",
            state="running",
            status="Up 1 hour",
        )
        assert cs.emoji == "🟢"
        assert cs.is_running is True
    
    def test_emoji_stopped(self):
        from app.models import ContainerSummary
        cs = ContainerSummary(
            id="x" * 64,
            name="test",
            image="test:latest",
            state="exited",
            status="Exited (0)",
        )
        assert cs.emoji == "🔴"
        assert cs.is_running is False
