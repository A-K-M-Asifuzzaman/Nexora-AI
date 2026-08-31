"""Forecast routes. Thin: authenticate, authorize, validate, one service call."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequirePermission, get_db
from app.core.context import TenantContext
from app.modules.forecasting.schemas import BacktestScoreResponse, ForecastPoint, ForecastResponse
from app.modules.forecasting.service import ForecastingService, InsufficientHistoryError
from app.modules.rbac.permissions import Perm

router = APIRouter(prefix="/forecasting", tags=["forecasting"])

Read = Annotated[TenantContext, Depends(RequirePermission(Perm.REPORTS_READ))]
Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("/products/{product_id}", response_model=None)
async def forecast_product(
    product_id: UUID,
    context: Read,
    session: Db,
    periods_ahead: Annotated[int, Query(ge=1, le=26)] = 4,
) -> ForecastResponse | JSONResponse:
    try:
        result = await ForecastingService(session, context).forecast(str(product_id), periods_ahead)
    except InsufficientHistoryError as error:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "INSUFFICIENT_HISTORY",
                "periods_available": error.periods_available,
                "periods_required": 8,
                "message": (
                    f"Only {error.periods_available} week(s) of sales history exist for this "
                    "product; at least 8 are needed for a forecast."
                ),
            },
        )
    return _serialize(result)


def _points(pairs: list[tuple[Any, float]]) -> list[ForecastPoint]:
    return [ForecastPoint(date=d, value=f"{v:.4f}") for d, v in pairs]


def _serialize(result: dict[str, Any]) -> ForecastResponse:
    return ForecastResponse(
        product_id=result["product_id"],
        periods_ahead=result["periods_ahead"],
        historical_actuals=_points(result["historical_actuals"]),
        point_forecast=_points(result["point_forecast"]),
        prediction_interval_low=_points(result["prediction_interval_low"]),
        prediction_interval_high=_points(result["prediction_interval_high"]),
        model_used=result["model_used"],
        backtest_scores=[
            BacktestScoreResponse(
                model=s.model_name,
                mae=f"{s.mae:.4f}",
                rmse=f"{s.rmse:.4f}",
                mase=f"{s.mase:.4f}" if s.mase is not None else None,
            )
            for s in result["backtest_scores"]
        ],
        limitation_note=result["limitation_note"],
    )
