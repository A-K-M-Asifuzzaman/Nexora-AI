"use client";

import { AlertOctagon, CheckCircle2, RefreshCw, XCircle } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

type Product = { id: string; sku: string; name: string; is_active: boolean };

type ForecastPoint = { date: string; value: string };
type BacktestScore = { model: string; mae: string; rmse: string; mase: string | null };
type ForecastResult = {
  product_id: string;
  periods_ahead: number;
  historical_actuals: ForecastPoint[];
  point_forecast: ForecastPoint[];
  prediction_interval_low: ForecastPoint[];
  prediction_interval_high: ForecastPoint[];
  model_used: string;
  backtest_scores: BacktestScore[];
  limitation_note: string;
};
type InsufficientHistory = {
  status: "INSUFFICIENT_HISTORY";
  periods_available: number;
  periods_required: number;
  message: string;
};

type Detector =
  | "REFUND_RATE"
  | "DISCOUNT_DEPTH"
  | "EXPENSE_SPIKE"
  | "REVENUE_DROP"
  | "STOCK_ADJUSTMENT_VOLUME"
  | "CASHIER_VOID_RATE";
type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
type AlertStatus = "OPEN" | "ACKNOWLEDGED" | "DISMISSED";
type Alert = {
  id: string;
  detector: Detector;
  severity: Severity;
  observed_value: string;
  expected_low: string;
  expected_high: string;
  deviation: string;
  reason: string;
  occurred_at: string;
  resource_type: "BRANCH" | "MEMBERSHIP" | "PRODUCT" | "TENANT";
  resource_id: string | null;
  label: string | null;
  status: AlertStatus;
};
type ApiError = { error?: { message?: string } };

const DETECTOR_LABELS: Record<Detector, string> = {
  REFUND_RATE: "Refund rate",
  DISCOUNT_DEPTH: "Discount depth",
  EXPENSE_SPIKE: "Expense spike",
  REVENUE_DROP: "Revenue drop",
  STOCK_ADJUSTMENT_VOLUME: "Stock adjustment volume",
  CASHIER_VOID_RATE: "Cashier void rate",
};

function csrfToken(): string {
  const value = document.cookie.split("; ").find((part) => part.startsWith("nexora_csrf="));
  return value ? decodeURIComponent(value.split("=").slice(1).join("=")) : "";
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/bff/${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(!["GET", "HEAD"].includes(init?.method ?? "GET") ? { "X-CSRF-Token": csrfToken() } : {}),
      ...init?.headers,
    },
  });
  const body = (await response.json()) as T & ApiError;
  if (!response.ok) throw new Error(body.error?.message ?? "The request could not be completed.");
  return body;
}

function isInsufficient(result: ForecastResult | InsufficientHistory): result is InsufficientHistory {
  return "status" in result && result.status === "INSUFFICIENT_HISTORY";
}

function SeverityBadge({ severity }: { severity: Severity }) {
  return <em className={`severity severity-${severity.toLowerCase()}`}>{severity}</em>;
}

export function InsightsPanel() {
  const [products, setProducts] = useState<Product[]>([]);
  const [productId, setProductId] = useState("");
  const [periodsAhead, setPeriodsAhead] = useState(4);
  const [forecastVisible, setForecastVisible] = useState(false);
  const [forecast, setForecast] = useState<ForecastResult | InsufficientHistory | null>(null);
  const [forecastBusy, setForecastBusy] = useState(false);
  const [forecastError, setForecastError] = useState<string | null>(null);

  const [alertsVisible, setAlertsVisible] = useState(false);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [statusFilter, setStatusFilter] = useState<AlertStatus | "ALL">("OPEN");
  const [alertsBusy, setAlertsBusy] = useState(false);
  const [alertsError, setAlertsError] = useState<string | null>(null);

  const loadProducts = useCallback(async () => {
    try {
      const page = await api<{ items: Product[] }>("products/");
      const active = (page.items ?? []).filter((product) => product.is_active);
      setProducts(active);
      setForecastVisible(active.length > 0);
      setProductId((current) => current || active[0]?.id || "");
    } catch {
      setForecastVisible(false);
    }
  }, []);

  const loadAlerts = useCallback(async (filter: AlertStatus | "ALL") => {
    setAlertsBusy(true);
    try {
      const query = filter === "ALL" ? "" : `?status=${filter}`;
      const items = await api<Alert[]>(`anomalies${query}`);
      setAlerts(items);
      setAlertsVisible(true);
      setAlertsError(null);
    } catch {
      setAlertsVisible(false);
    } finally {
      setAlertsBusy(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadProducts();
      void loadAlerts("OPEN");
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadProducts, loadAlerts]);

  // The catalog lives in a sibling panel with its own independent state, so a
  // product created there wouldn't otherwise be visible here until a reload.
  useEffect(() => {
    const onProductsChanged = () => void loadProducts();
    window.addEventListener("nexora:products-changed", onProductsChanged);
    return () => window.removeEventListener("nexora:products-changed", onProductsChanged);
  }, [loadProducts]);

  const runForecast = useCallback(async (id: string, periods: number) => {
    if (!id) return;
    setForecastBusy(true);
    setForecastError(null);
    try {
      const result = await api<ForecastResult | InsufficientHistory>(
        `forecasting/products/${id}?periods_ahead=${periods}`,
      );
      setForecast(result);
    } catch (reason) {
      setForecast(null);
      setForecastError(reason instanceof Error ? reason.message : "The forecast could not be generated.");
    } finally {
      setForecastBusy(false);
    }
  }, []);

  useEffect(() => {
    if (!productId) return;
    const timer = window.setTimeout(() => void runForecast(productId, periodsAhead), 0);
    return () => window.clearTimeout(timer);
  }, [productId, periodsAhead, runForecast]);

  async function actOnAlert(id: string, action: "acknowledge" | "dismiss") {
    setAlertsBusy(true);
    setAlertsError(null);
    try {
      const updated = await api<Alert>(`anomalies/${id}/${action}`, { method: "POST" });
      setAlerts((prev) =>
        statusFilter === "ALL"
          ? prev.map((alert) => (alert.id === id ? updated : alert))
          : prev.filter((alert) => alert.id !== id),
      );
    } catch (reason) {
      setAlertsError(reason instanceof Error ? reason.message : "The alert could not be updated.");
    } finally {
      setAlertsBusy(false);
    }
  }

  async function runDetectors() {
    setAlertsBusy(true);
    setAlertsError(null);
    try {
      await api<{ alerts_created: number }>("anomalies/run", { method: "POST" });
      await loadAlerts(statusFilter);
    } catch (reason) {
      setAlertsError(reason instanceof Error ? reason.message : "Detectors could not be run.");
      setAlertsBusy(false);
    }
  }

  const chart = useMemo(() => {
    if (!forecast || isInsufficient(forecast)) return null;
    const actuals = forecast.historical_actuals.slice(-12);
    const bars = [
      ...actuals.map((point) => ({ ...point, kind: "actual" as const })),
      ...forecast.point_forecast.map((point) => ({ ...point, kind: "forecast" as const })),
    ];
    const ceiling = Math.max(
      1,
      ...bars.map((point) => Number(point.value)),
      ...forecast.prediction_interval_high.map((point) => Number(point.value)),
    );
    return { bars, ceiling };
  }, [forecast]);

  return (
    <>
      <section id="forecast" className="management-card">
        {!forecastVisible && (
          <>
            <div className="section-title">
              <div>
                <small>DEMAND</small>
                <h2>Forecast</h2>
              </div>
            </div>
            <p className="empty-state">No products are available to forecast yet.</p>
          </>
        )}
        {forecastVisible && (
          <>
            <div className="section-title">
              <div>
                <small>DEMAND</small>
                <h2>Forecast</h2>
              </div>
              <span>{forecast && !isInsufficient(forecast) ? `Model: ${forecast.model_used}` : ""}</span>
            </div>

            <div className="insights-controls">
              <select
                aria-label="Product to forecast"
                value={productId}
                onChange={(event) => setProductId(event.target.value)}
              >
                {products.map((product) => (
                  <option key={product.id} value={product.id}>
                    {product.name} ({product.sku})
                  </option>
                ))}
              </select>
              <label>
                Weeks ahead
                <input
                  aria-label="Periods ahead"
                  type="number"
                  min={1}
                  max={26}
                  value={periodsAhead}
                  onChange={(event) => setPeriodsAhead(Math.min(26, Math.max(1, Number(event.target.value) || 1)))}
                />
              </label>
            </div>

            {forecastError && <p role="alert" className="workspace-error">{forecastError}</p>}
            {forecastBusy && <p className="empty-state">Forecasting…</p>}

            {!forecastBusy && forecast && isInsufficient(forecast) && (
              <p className="empty-state" role="status">
                {forecast.message}
              </p>
            )}

            {!forecastBusy && forecast && !isInsufficient(forecast) && chart && (
              <>
                <div className="large-chart insights-chart">
                  {chart.bars.map((point, index) => (
                    <i
                      key={`${point.date}-${index}`}
                      className={point.kind === "forecast" ? "forecast" : "active"}
                      style={{ height: `${Math.max(2, (Number(point.value) / chart.ceiling) * 100)}%` }}
                      title={`${point.date}: ${point.value}`}
                    />
                  ))}
                </div>
                <p className="chart-legend">
                  <span><i className="active" />Actual (last {Math.min(12, forecast.historical_actuals.length)} weeks)</span>
                  <span><i className="forecast" />Forecast ({forecast.periods_ahead} weeks)</span>
                </p>

                <div className="score-table" role="region" aria-label="Forecast values" tabIndex={0}>
                  <div className="score-head">
                    <span>Week</span>
                    <span>Forecast</span>
                    <span>Low</span>
                    <span>High</span>
                  </div>
                  {forecast.point_forecast.map((point, index) => (
                    <div key={point.date}>
                      <span>{point.date}</span>
                      <span>{point.value}</span>
                      <span>{forecast.prediction_interval_low[index]?.value}</span>
                      <span>{forecast.prediction_interval_high[index]?.value}</span>
                    </div>
                  ))}
                </div>

                <div className="score-table backtest-table" role="region" aria-label="Forecast model scores" tabIndex={0}>
                  <div className="score-head">
                    <span>Model</span>
                    <span>MAE</span>
                    <span>RMSE</span>
                    <span>MASE</span>
                  </div>
                  {forecast.backtest_scores.map((score) => (
                    <div key={score.model} className={score.model === forecast.model_used ? "winner" : ""}>
                      <span>{score.model}</span>
                      <span>{score.mae}</span>
                      <span>{score.rmse}</span>
                      <span>{score.mase ?? "—"}</span>
                    </div>
                  ))}
                </div>

                <p className="empty-state">{forecast.limitation_note}</p>
              </>
            )}
          </>
        )}
      </section>

      {alertsVisible && (
        <section id="anomalies" className="management-card">
          <div className="section-title">
            <div>
              <small>OVERSIGHT</small>
              <h2>Anomaly alerts</h2>
            </div>
            <button disabled={alertsBusy} onClick={() => void runDetectors()}>
              <RefreshCw />
              Run detectors now
            </button>
          </div>

          <div className="insights-controls">
            <select
              aria-label="Alert status filter"
              value={statusFilter}
              onChange={(event) => {
                const next = event.target.value as AlertStatus | "ALL";
                setStatusFilter(next);
                void loadAlerts(next);
              }}
            >
              <option value="OPEN">Open</option>
              <option value="ACKNOWLEDGED">Acknowledged</option>
              <option value="DISMISSED">Dismissed</option>
              <option value="ALL">All</option>
            </select>
          </div>

          {alertsError && <p role="alert" className="workspace-error">{alertsError}</p>}

          <div className="branch-list alert-list">
            {alerts.length === 0 && <p className="empty-state">No anomalies in this view.</p>}
            {alerts.map((alert) => (
              <article key={alert.id}>
                <span className="branch-icon">
                  <AlertOctagon />
                </span>
                <div>
                  <strong>
                    {DETECTOR_LABELS[alert.detector]}
                    {alert.label ? ` · ${alert.label}` : ""}
                  </strong>
                  <small>
                    {alert.reason} · observed {alert.observed_value} (expected {alert.expected_low}–
                    {alert.expected_high}) · {new Date(alert.occurred_at).toLocaleString()}
                  </small>
                </div>
                <SeverityBadge severity={alert.severity} />
                {alert.status === "OPEN" && (
                  <>
                    <button
                      className="row-action"
                      disabled={alertsBusy}
                      onClick={() => void actOnAlert(alert.id, "acknowledge")}
                      aria-label={`Acknowledge ${DETECTOR_LABELS[alert.detector]} alert`}
                      title="Acknowledge"
                    >
                      <CheckCircle2 />
                    </button>
                    <button
                      className="row-action"
                      disabled={alertsBusy}
                      onClick={() => void actOnAlert(alert.id, "dismiss")}
                      aria-label={`Dismiss ${DETECTOR_LABELS[alert.detector]} alert`}
                      title="Dismiss"
                    >
                      <XCircle />
                    </button>
                  </>
                )}
                {alert.status !== "OPEN" && <em className="pending">{alert.status.toLowerCase()}</em>}
              </article>
            ))}
          </div>
        </section>
      )}
    </>
  );
}
