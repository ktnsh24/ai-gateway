"""
AI Gateway — Usage Dashboard Endpoint

GET /v1/usage — Cost and usage dashboard.
Shows total requests, tokens, costs, cache hit rates, and breakdowns by model/provider.
"""

from fastapi import APIRouter, Query, Request

from src.models import UsagePeriod, UsageResponse, UsageSummary

router = APIRouter(prefix="/v1", tags=["usage"])


@router.get("/usage", response_model=UsageResponse)
async def get_usage(
    request: Request,
    period: UsagePeriod = Query(default=UsagePeriod.TODAY, description="Time period"),
) -> UsageResponse:
    """Get usage summary for the specified period."""
    cost_tracker = request.app.state.cost_tracker
    settings = request.app.state.settings

    api_key = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not api_key:
        api_key = settings.master_api_key

    summary_data = await cost_tracker.get_usage_summary(
        api_key=api_key,
        period=period.value,
    )

    return UsageResponse(
        summary=UsageSummary(**summary_data),
        api_key=api_key[:8] + "..." if api_key else "",
    )
