"""
visualizer.py — Job application stats visualization using graphify.

Generates charts for:
  • Applications over time (line graph)
  • Jobs by source (bar chart)
  • Match score distribution (histogram)
  • Success rate by company
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select, func
from graphify import BarChart, LineChart, PieChart
from database import Job, AsyncSessionLocal


async def get_jobs_by_source() -> dict[str, int]:
    """Count jobs by source (RemoteOK, Remotive, etc.)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Job.source, func.count(Job.id).label('count'))
            .group_by(Job.source)
        )
        return {row[0]: row[1] for row in result.fetchall()}


async def get_applications_over_time(days: int = 30) -> dict[str, int]:
    """
    Count applications per day for last N days.
    Returns {"2025-05-20": 5, "2025-05-21": 3, ...}
    """
    async with AsyncSessionLocal() as session:
        start_date = datetime.utcnow() - timedelta(days=days)
        result = await session.execute(
            select(
                func.date(Job.applied_at).label('date'),
                func.count(Job.id).label('count')
            )
            .where(Job.applied_at >= start_date)
            .group_by(func.date(Job.applied_at))
            .order_by(func.date(Job.applied_at))
        )
        return {str(row[0]): row[1] for row in result.fetchall()}


async def get_match_score_distribution() -> dict[str, int]:
    """Distribution of job match scores (0.0-0.2, 0.2-0.4, etc.)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Job.match_score)
        )
        scores = [row[0] for row in result.fetchall()]
        
        # Bucket into 5 ranges
        buckets = {
            "0.0-0.2": 0,
            "0.2-0.4": 0,
            "0.4-0.6": 0,
            "0.6-0.8": 0,
            "0.8-1.0": 0,
        }
        
        for score in scores:
            if score < 0.2:
                buckets["0.0-0.2"] += 1
            elif score < 0.4:
                buckets["0.2-0.4"] += 1
            elif score < 0.6:
                buckets["0.4-0.6"] += 1
            elif score < 0.8:
                buckets["0.6-0.8"] += 1
            else:
                buckets["0.8-1.0"] += 1
        
        return buckets


def generate_jobs_by_source_chart(data: dict[str, int]) -> str:
    """Generate bar chart of jobs by source."""
    if not data:
        return "No data available"
    
    chart = BarChart(
        title="Jobs by Source",
        x_axis_label="Source",
        y_axis_label="Count",
        data=data,
    )
    return chart.render()


def generate_applications_timeline(data: dict[str, int]) -> str:
    """Generate line chart of applications over time."""
    if not data:
        return "No data available"
    
    # Ensure chronological order
    sorted_data = dict(sorted(data.items()))
    
    chart = LineChart(
        title="Applications Over Time",
        x_axis_label="Date",
        y_axis_label="Applications",
        data=sorted_data,
    )
    return chart.render()


def generate_match_score_histogram(data: dict[str, int]) -> str:
    """Generate histogram of match score distribution."""
    if not data:
        return "No data available"
    
    chart = BarChart(
        title="Match Score Distribution",
        x_axis_label="Score Range",
        y_axis_label="Count",
        data=data,
    )
    return chart.render()


async def generate_stats_summary() -> dict:
    """Generate comprehensive stats summary as dict (for JSON response)."""
    async with AsyncSessionLocal() as session:
        # Total jobs
        total_jobs = (await session.execute(
            select(func.count(Job.id))
        )).scalar()
        
        # Applied vs pending
        applied_jobs = (await session.execute(
            select(func.count(Job.id)).where(Job.applied_at.isnot(None))
        )).scalar()
        
        pending_jobs = total_jobs - applied_jobs
        
        # By source
        by_source = await get_jobs_by_source()
        
        # Average match score
        avg_score = (await session.execute(
            select(func.avg(Job.match_score))
        )).scalar() or 0
        
        # Success rate (applications that resulted in offers, if tracked)
        # For now, just tracking applied vs pending
        success_rate = (applied_jobs / total_jobs * 100) if total_jobs > 0 else 0
        
        return {
            "total_jobs": total_jobs,
            "applied": applied_jobs,
            "pending": pending_jobs,
            "average_match_score": round(avg_score, 3),
            "success_rate_percent": round(success_rate, 1),
            "by_source": by_source,
        }


async def export_stats_json() -> dict:
    """Export all stats as JSON-serializable dict."""
    summary = await generate_stats_summary()
    timeline = await get_applications_over_time(30)
    match_dist = await get_match_score_distribution()
    
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "summary": summary,
        "timeline_30_days": timeline,
        "match_score_distribution": match_dist,
    }
