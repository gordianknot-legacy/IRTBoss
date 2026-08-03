"""
Report generation for IRTBoss.

Generates reports in multiple formats (HTML, JSON, PDF) containing:
- Executive summary
- Model selection justification
- Item parameters
- Diagnostic visualizations
- Reproducibility metadata
"""

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

# Template directory
TEMPLATE_DIR = Path(__file__).parent / "templates"


@dataclass
class ReportData:
    """Data structure for report content."""
    project_id: str
    project_name: str
    project_description: Optional[str]
    stakes_level: str
    intended_use: str

    # Data summary
    n_respondents: int
    n_items: int
    response_type: str
    missing_percentage: float

    # Model selection
    recommended_model: str
    models_compared: list[str]
    selection_reasons: list[str]
    comparison_table: dict[str, dict[str, float]]

    # Reliability
    reliability_estimate: float
    reliability_threshold: float
    reliability_acceptable: bool

    # Item parameters
    item_parameters: list[dict[str, Any]]
    n_flagged_items: int
    flagged_items: list[str]

    # Recommendations
    recommendations: list[dict[str, Any]]
    overall_assessment: str
    is_ready_for_use: bool

    # Metadata
    generated_at: str
    software_version: str
    data_hash: Optional[str] = None


class ReportGenerator:
    """Generate reports in various formats."""

    def __init__(self, output_dir: Path | str = "/app/reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Set up Jinja2 environment
        if TEMPLATE_DIR.exists():
            self.env = Environment(
                loader=FileSystemLoader(str(TEMPLATE_DIR)),
                autoescape=select_autoescape(['html', 'xml']),
            )
        else:
            self.env = None
            logger.warning(f"Template directory not found: {TEMPLATE_DIR}")

    def generate_html(self, data: ReportData) -> str:
        """Generate HTML report."""
        if self.env is None:
            # Use inline template if no template directory
            return self._generate_html_inline(data)

        try:
            template = self.env.get_template("report.html")
            return template.render(data=data)
        except Exception as e:
            logger.warning(f"Error loading template: {e}, using inline")
            return self._generate_html_inline(data)

    def _generate_html_inline(self, data: ReportData) -> str:
        """Generate HTML report using inline template."""
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IRT Analysis Report - {data.project_name}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 900px; margin: 0 auto; padding: 40px 20px; }}
        h1 {{ font-size: 28px; margin-bottom: 8px; color: #111; }}
        h2 {{ font-size: 20px; margin: 32px 0 16px; padding-bottom: 8px; border-bottom: 2px solid #e5e7eb; color: #111; }}
        h3 {{ font-size: 16px; margin: 24px 0 12px; color: #374151; }}
        p {{ margin-bottom: 12px; }}
        .subtitle {{ color: #6b7280; font-size: 14px; margin-bottom: 32px; }}
        .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin: 24px 0; }}
        .summary-card {{ background: #f9fafb; border-radius: 8px; padding: 16px; }}
        .summary-card .label {{ font-size: 12px; color: #6b7280; text-transform: uppercase; }}
        .summary-card .value {{ font-size: 24px; font-weight: 600; margin-top: 4px; }}
        .badge {{ display: inline-block; padding: 4px 12px; border-radius: 16px; font-size: 12px; font-weight: 500; }}
        .badge-green {{ background: #d1fae5; color: #065f46; }}
        .badge-yellow {{ background: #fef3c7; color: #92400e; }}
        .badge-red {{ background: #fee2e2; color: #991b1b; }}
        table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #e5e7eb; }}
        th {{ background: #f9fafb; font-weight: 600; font-size: 12px; text-transform: uppercase; color: #6b7280; }}
        td {{ font-size: 14px; }}
        .text-right {{ text-align: right; }}
        .text-center {{ text-align: center; }}
        .mono {{ font-family: monospace; }}
        .recommendation {{ background: #f9fafb; border-left: 4px solid #3b82f6; padding: 16px; margin: 16px 0; border-radius: 0 8px 8px 0; }}
        .recommendation.critical {{ border-color: #ef4444; }}
        .recommendation.high {{ border-color: #f59e0b; }}
        .recommendation.medium {{ border-color: #3b82f6; }}
        .recommendation.low {{ border-color: #6b7280; }}
        .recommendation-title {{ font-weight: 600; margin-bottom: 8px; }}
        .recommendation-action {{ color: #374151; margin-top: 8px; }}
        .metadata {{ margin-top: 48px; padding-top: 24px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #6b7280; }}
        .ready-badge {{ font-size: 14px; padding: 8px 16px; }}
        @media print {{
            body {{ padding: 20px; }}
            .no-print {{ display: none; }}
        }}
    </style>
</head>
<body>
    <h1>{data.project_name}</h1>
    <p class="subtitle">{data.project_description or 'IRT Analysis Report'}</p>

    <div class="summary-grid">
        <div class="summary-card">
            <div class="label">Respondents</div>
            <div class="value">{data.n_respondents:,}</div>
        </div>
        <div class="summary-card">
            <div class="label">Items</div>
            <div class="value">{data.n_items}</div>
        </div>
        <div class="summary-card">
            <div class="label">Reliability</div>
            <div class="value">{data.reliability_estimate:.2f}</div>
        </div>
        <div class="summary-card">
            <div class="label">Recommended Model</div>
            <div class="value">{data.recommended_model}</div>
        </div>
    </div>

    <div style="margin: 24px 0;">
        <span class="badge {'badge-green' if data.is_ready_for_use else 'badge-red'} ready-badge">
            {'Ready for Use' if data.is_ready_for_use else 'Requires Review'}
        </span>
    </div>

    <h2>Executive Summary</h2>
    <p>{data.overall_assessment}</p>

    <h2>Assessment Context</h2>
    <table>
        <tr><td><strong>Stakes Level</strong></td><td class="text-right">{data.stakes_level.title()}</td></tr>
        <tr><td><strong>Intended Use</strong></td><td class="text-right">{data.intended_use.title()}</td></tr>
        <tr><td><strong>Response Type</strong></td><td class="text-right">{data.response_type.title()}</td></tr>
        <tr><td><strong>Missing Data</strong></td><td class="text-right">{data.missing_percentage:.1%}</td></tr>
    </table>

    <h2>Model Selection</h2>
    <p>The <strong>{data.recommended_model}</strong> model was selected based on the following criteria:</p>
    <ul style="margin: 12px 0 12px 24px;">
        {''.join(f'<li>{reason}</li>' for reason in data.selection_reasons)}
    </ul>

    <h3>Model Comparison</h3>
    <table>
        <thead>
            <tr>
                <th>Model</th>
                <th class="text-right">Log-Likelihood</th>
                <th class="text-right">AIC</th>
                <th class="text-right">BIC</th>
                <th class="text-right"># Parameters</th>
            </tr>
        </thead>
        <tbody>
            {''.join(f'''
            <tr>
                <td><strong>{model}</strong></td>
                <td class="text-right mono">{stats.get('log_likelihood', 0):.1f}</td>
                <td class="text-right mono">{stats.get('aic', 0):.1f}</td>
                <td class="text-right mono">{stats.get('bic', 0):.1f}</td>
                <td class="text-right">{stats.get('n_parameters', 0)}</td>
            </tr>
            ''' for model, stats in data.comparison_table.items())}
        </tbody>
    </table>

    <h2>Reliability Analysis</h2>
    <p>
        The estimated reliability is <strong>{data.reliability_estimate:.2f}</strong>,
        which is {'above' if data.reliability_acceptable else 'below'} the threshold of
        {data.reliability_threshold:.2f} for {data.stakes_level} stakes assessments.
    </p>

    <h2>Item Parameters</h2>
    <p>
        {data.n_flagged_items} of {data.n_items} items were flagged for potential issues.
        {f"Flagged items: {', '.join(data.flagged_items)}" if data.flagged_items else ''}
    </p>
    <table>
        <thead>
            <tr>
                <th>Item</th>
                <th class="text-center">Status</th>
                <th class="text-right">Discrimination (a)</th>
                <th class="text-right">Difficulty (b)</th>
                <th class="text-right">Guessing (c)</th>
            </tr>
        </thead>
        <tbody>
            {''.join(f'''
            <tr>
                <td>{item.get('item_id', 'N/A')}</td>
                <td class="text-center">
                    <span class="badge {'badge-green' if item.get('status') == 'good' else 'badge-yellow' if item.get('status') in ['acceptable', 'flagged'] else 'badge-red'}">
                        {item.get('status', 'unknown').title()}
                    </span>
                </td>
                <td class="text-right mono">{item.get('discrimination', 1.0):.2f}</td>
                <td class="text-right mono">{item.get('difficulty', 0.0):.2f}</td>
                <td class="text-right mono">{item.get('guessing', 0.0):.2f}</td>
            </tr>
            ''' for item in data.item_parameters[:20])}
            {f'<tr><td colspan="5" class="text-center" style="color: #6b7280;">... and {len(data.item_parameters) - 20} more items</td></tr>' if len(data.item_parameters) > 20 else ''}
        </tbody>
    </table>

    <h2>Recommendations</h2>
    {''.join(f'''
    <div class="recommendation {rec.get('priority', 'medium')}">
        <div class="recommendation-title">{rec.get('title', 'Recommendation')}</div>
        <p>{rec.get('description', '')}</p>
        <div class="recommendation-action"><strong>Action:</strong> {rec.get('action', '')}</div>
    </div>
    ''' for rec in data.recommendations) if data.recommendations else '<p>No specific recommendations at this time.</p>'}

    <div class="metadata">
        <h3>Report Metadata</h3>
        <p>Generated: {data.generated_at}</p>
        <p>Software Version: {data.software_version}</p>
        {f'<p>Data Hash: {data.data_hash}</p>' if data.data_hash else ''}
        <p>Project ID: {data.project_id}</p>
    </div>
</body>
</html>"""
        return html

    def generate_json(self, data: ReportData) -> str:
        """Generate JSON report."""
        return json.dumps(asdict(data), indent=2)

    def generate_pdf(self, data: ReportData) -> bytes:
        """
        Generate PDF report.

        Requires WeasyPrint to be installed.
        Falls back to HTML if WeasyPrint is not available.
        """
        try:
            from weasyprint import HTML
            html_content = self.generate_html(data)
            return HTML(string=html_content).write_pdf()
        except ImportError:
            logger.warning("WeasyPrint not installed, PDF generation not available")
            raise RuntimeError(
                "PDF generation requires WeasyPrint. "
                "Install with: pip install weasyprint"
            )
        except Exception as e:
            logger.exception("Error generating PDF")
            raise RuntimeError(f"Error generating PDF: {e}")

    def save_report(
        self,
        data: ReportData,
        format: str,
        filename: Optional[str] = None,
    ) -> Path:
        """
        Save report to file.

        Args:
            data: Report data
            format: Output format (html, json, pdf)
            filename: Optional custom filename (without extension)

        Returns:
            Path to saved file
        """
        if filename is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"report_{data.project_id[:8]}_{timestamp}"

        format = format.lower()

        if format == "html":
            content = self.generate_html(data)
            filepath = self.output_dir / f"{filename}.html"
            filepath.write_text(content, encoding="utf-8")
        elif format == "json":
            content = self.generate_json(data)
            filepath = self.output_dir / f"{filename}.json"
            filepath.write_text(content, encoding="utf-8")
        elif format == "pdf":
            content = self.generate_pdf(data)
            filepath = self.output_dir / f"{filename}.pdf"
            filepath.write_bytes(content)
        else:
            raise ValueError(f"Unsupported format: {format}")

        logger.info(f"Report saved to: {filepath}")
        return filepath


def create_mock_report_data(project_id: str = "test-project") -> ReportData:
    """Create mock report data for testing."""
    return ReportData(
        project_id=project_id,
        project_name="Sample Assessment",
        project_description="A demonstration IRT analysis report",
        stakes_level="medium",
        intended_use="operational",
        n_respondents=500,
        n_items=20,
        response_type="dichotomous",
        missing_percentage=0.02,
        recommended_model="2PL",
        models_compared=["1PL", "2PL"],
        selection_reasons=[
            "BIC favors 2PL over 1PL by 45 points",
            "Items show varying discrimination, supporting 2PL",
            "Sample size adequate for 2PL estimation",
        ],
        comparison_table={
            "1PL": {"log_likelihood": -5000, "aic": 10040, "bic": 10124, "n_parameters": 20},
            "2PL": {"log_likelihood": -4850, "aic": 9780, "bic": 9948, "n_parameters": 40},
        },
        reliability_estimate=0.85,
        reliability_threshold=0.80,
        reliability_acceptable=True,
        item_parameters=[
            {"item_id": f"item_{i:02d}", "discrimination": 1.0 + (i % 5) * 0.2, "difficulty": -2 + i * 0.2, "guessing": 0, "status": "good" if i % 5 != 0 else "flagged"}
            for i in range(1, 21)
        ],
        n_flagged_items=4,
        flagged_items=["item_05", "item_10", "item_15", "item_20"],
        recommendations=[
            {
                "priority": "medium",
                "category": "Item Quality",
                "title": "Review flagged items",
                "description": "4 items have low discrimination values that may reduce test precision.",
                "action": "Consider revising or removing items: item_05, item_10, item_15, item_20",
            },
        ],
        overall_assessment="The assessment demonstrates acceptable psychometric properties for operational use. The 2PL model provides good fit, and reliability exceeds the threshold for medium-stakes testing. Some items should be reviewed for potential improvement.",
        is_ready_for_use=True,
        generated_at=datetime.utcnow().isoformat(),
        software_version="0.1.0",
    )
