"""
Alerting Module for Job Scraper
--------------------------------
Sends email alerts when:
- Scraper run fails or has high error rate
- Company repeatedly fails to scrape
- No jobs found for extended period
- Critical errors occur
"""

import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from os.path import join, dirname

# Load environment variables
dotenv_path = join(dirname(__file__), '.env')
load_dotenv(dotenv_path)

logger = logging.getLogger(__name__)

# Alert configuration
ALERT_EMAIL = os.environ.get("Email_adddress", "")
ALERT_PASSWORD = os.environ.get("Email_password", "")
ALERT_RECIPIENTS = [ALERT_EMAIL]  # Add more recipients as needed
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://localhost:5050")

# Alert thresholds
ERROR_RATE_THRESHOLD = 0.2  # 20% error rate triggers alert
CONSECUTIVE_FAILURE_THRESHOLD = 5  # Company fails 5 times in a row
NO_JOBS_HOURS_THRESHOLD = 24  # Alert if no jobs found in 24 hours
MIN_COMPANIES_FOR_ALERT = 10  # Only alert if processing at least this many companies


class AlertType:
    HIGH_ERROR_RATE = "high_error_rate"
    COMPANY_FAILURES = "company_failures"
    NO_JOBS_FOUND = "no_jobs_found"
    SCRAPER_CRASH = "scraper_crash"
    CRITICAL_ERROR = "critical_error"


def send_alert_email(
    subject: str,
    body: str,
    alert_type: str,
    recipients: List[str] = None
) -> bool:
    """
    Send an alert email.
    
    Args:
        subject: Email subject
        body: Email body (HTML supported)
        alert_type: Type of alert for categorization
        recipients: List of email recipients (defaults to ALERT_RECIPIENTS)
    
    Returns:
        True if email sent successfully, False otherwise
    """
    if not ALERT_PASSWORD:
        logger.warning("Alert email password not configured, skipping alert")
        return False
    
    recipients = recipients or ALERT_RECIPIENTS
    
    try:
        msg = MIMEMultipart("alternative")
        msg['From'] = ALERT_EMAIL
        msg['To'] = ", ".join(recipients)
        msg['Subject'] = f"[Scraper Alert - {alert_type.upper()}] {subject}"
        
        # Create HTML body
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .alert-box {{ 
                    padding: 15px; 
                    margin: 10px 0; 
                    border-radius: 5px;
                }}
                .error {{ background-color: #ffebee; border: 1px solid #f44336; }}
                .warning {{ background-color: #fff3e0; border: 1px solid #ff9800; }}
                .info {{ background-color: #e3f2fd; border: 1px solid #2196f3; }}
                table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
                .timestamp {{ color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <h2>Job Scraper Alert</h2>
            <p class="timestamp">Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <div class="alert-box {'error' if 'error' in alert_type or 'crash' in alert_type else 'warning'}">
                {body}
            </div>
            <hr>
            <p style="color: #666; font-size: 11px;">
                This is an automated alert from the Job Scraper system.<br>
                Dashboard: <a href="{DASHBOARD_URL}">{DASHBOARD_URL}</a>
            </p>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(html, 'html'))
        
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(ALERT_EMAIL, ALERT_PASSWORD)
            server.sendmail(ALERT_EMAIL, recipients, msg.as_string())
        
        logger.info(f"Alert email sent: {subject}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send alert email: {e}")
        return False


def alert_high_error_rate(
    total_companies: int,
    failed_companies: int,
    error_messages: List[str],
    log_file: str = None
) -> bool:
    """
    Send alert when error rate exceeds threshold.
    
    Args:
        total_companies: Total companies processed
        failed_companies: Number of companies that failed
        error_messages: List of error messages (top 10)
        log_file: Path to the log file
    """
    if total_companies < MIN_COMPANIES_FOR_ALERT:
        return False
    
    error_rate = failed_companies / total_companies
    if error_rate < ERROR_RATE_THRESHOLD:
        return False
    
    errors_html = "<br>".join(f"• {err[:100]}..." if len(err) > 100 else f"• {err}" 
                              for err in error_messages[:10])
    
    body = f"""
    <h3>High Error Rate Detected</h3>
    <table>
        <tr><th>Metric</th><th>Value</th></tr>
        <tr><td>Total Companies</td><td>{total_companies}</td></tr>
        <tr><td>Failed Companies</td><td>{failed_companies}</td></tr>
        <tr><td>Error Rate</td><td><strong>{error_rate:.1%}</strong></td></tr>
        <tr><td>Threshold</td><td>{ERROR_RATE_THRESHOLD:.1%}</td></tr>
        {f'<tr><td>Log File</td><td>{log_file}</td></tr>' if log_file else ''}
    </table>
    
    <h4>Recent Errors:</h4>
    <div style="background: #f5f5f5; padding: 10px; font-family: monospace; font-size: 12px;">
        {errors_html}
    </div>
    """
    
    return send_alert_email(
        subject=f"Error rate {error_rate:.1%} exceeds threshold",
        body=body,
        alert_type=AlertType.HIGH_ERROR_RATE
    )


def alert_company_failures(
    failed_companies: List[Dict[str, Any]]
) -> bool:
    """
    Send alert when companies have repeated failures.
    
    Args:
        failed_companies: List of company dicts with failure info
    """
    if not failed_companies:
        return False
    
    rows = ""
    for company in failed_companies[:20]:  # Limit to 20 companies
        rows += f"""
        <tr>
            <td>{company.get('company', 'Unknown')}</td>
            <td>{company.get('link_type', 'Unknown')}</td>
            <td>{company.get('consecutive_failures', 0)}</td>
            <td>{company.get('last_error', 'N/A')[:50]}...</td>
            <td>{company.get('last_success', 'Never')}</td>
        </tr>
        """
    
    body = f"""
    <h3>Companies With Repeated Failures</h3>
    <p>The following {len(failed_companies)} companies have failed {CONSECUTIVE_FAILURE_THRESHOLD}+ times consecutively:</p>
    <table>
        <tr>
            <th>Company</th>
            <th>ATS Type</th>
            <th>Consecutive Failures</th>
            <th>Last Error</th>
            <th>Last Success</th>
        </tr>
        {rows}
    </table>
    <p><strong>Action Required:</strong> Review these companies and consider:</p>
    <ul>
        <li>Checking if the career page URL has changed</li>
        <li>Verifying the ATS type is correct</li>
        <li>Temporarily deactivating if the company is no longer relevant</li>
    </ul>
    """
    
    return send_alert_email(
        subject=f"{len(failed_companies)} companies with repeated failures",
        body=body,
        alert_type=AlertType.COMPANY_FAILURES
    )


def alert_no_jobs_found(
    last_job_time: datetime,
    hours_since: float
) -> bool:
    """
    Send alert when no jobs have been found for extended period.
    
    Args:
        last_job_time: When jobs were last found
        hours_since: Hours since jobs were found
    """
    if hours_since < NO_JOBS_HOURS_THRESHOLD:
        return False
    
    body = f"""
    <h3>No Jobs Found Alert</h3>
    <p>The scraper has not found any matching jobs in the last <strong>{hours_since:.1f} hours</strong>.</p>
    <table>
        <tr><th>Metric</th><th>Value</th></tr>
        <tr><td>Last Job Found</td><td>{last_job_time.strftime('%Y-%m-%d %H:%M:%S') if last_job_time else 'Unknown'}</td></tr>
        <tr><td>Hours Since</td><td>{hours_since:.1f}</td></tr>
        <tr><td>Alert Threshold</td><td>{NO_JOBS_HOURS_THRESHOLD} hours</td></tr>
    </table>
    <p><strong>Possible Causes:</strong></p>
    <ul>
        <li>Search keywords may be too restrictive</li>
        <li>ATS APIs may have changed</li>
        <li>Network connectivity issues</li>
        <li>All matching jobs already sent</li>
    </ul>
    """
    
    return send_alert_email(
        subject=f"No jobs found in {hours_since:.0f} hours",
        body=body,
        alert_type=AlertType.NO_JOBS_FOUND
    )


def alert_scraper_crash(
    error_message: str,
    stack_trace: str = None,
    context: Dict[str, Any] = None
) -> bool:
    """
    Send alert when scraper crashes unexpectedly.
    
    Args:
        error_message: The error message
        stack_trace: Full stack trace if available
        context: Additional context (current company, etc.)
    """
    context_html = ""
    if context:
        context_rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in context.items())
        context_html = f"""
        <h4>Context:</h4>
        <table>{context_rows}</table>
        """
    
    body = f"""
    <h3>Scraper Crashed!</h3>
    <p style="color: red;"><strong>Error:</strong> {error_message}</p>
    
    {context_html}
    
    {f'''<h4>Stack Trace:</h4>
    <pre style="background: #f5f5f5; padding: 10px; overflow-x: auto; font-size: 11px;">
{stack_trace}
    </pre>''' if stack_trace else ''}
    
    <p><strong>Action Required:</strong> Check the logs and restart the scraper if necessary.</p>
    """
    
    return send_alert_email(
        subject="Scraper crashed - immediate attention required",
        body=body,
        alert_type=AlertType.SCRAPER_CRASH
    )


def alert_critical_error(
    error_type: str,
    error_message: str,
    details: str = None
) -> bool:
    """
    Send alert for critical errors (DB connection, API failures, etc.)
    
    Args:
        error_type: Type of error (db_connection, api_failure, etc.)
        error_message: Error message
        details: Additional details
    """
    body = f"""
    <h3>Critical Error: {error_type}</h3>
    <div class="alert-box error">
        <p><strong>Error:</strong> {error_message}</p>
    </div>
    
    {f'<p><strong>Details:</strong> {details}</p>' if details else ''}
    
    <p><strong>This error may prevent the scraper from functioning correctly.</strong></p>
    """
    
    return send_alert_email(
        subject=f"Critical error: {error_type}",
        body=body,
        alert_type=AlertType.CRITICAL_ERROR
    )


class AlertManager:
    """
    Manages alert state to prevent alert fatigue (rate limiting).
    """
    
    def __init__(self):
        self._last_alerts: Dict[str, datetime] = {}
        self._alert_cooldown = timedelta(hours=2)  # Don't repeat same alert for 2 hours
    
    def can_send_alert(self, alert_type: str, identifier: str = "") -> bool:
        """Check if we can send an alert (not in cooldown)."""
        key = f"{alert_type}:{identifier}"
        last_sent = self._last_alerts.get(key)
        
        if last_sent and datetime.now() - last_sent < self._alert_cooldown:
            return False
        return True
    
    def mark_alert_sent(self, alert_type: str, identifier: str = ""):
        """Mark that an alert was sent."""
        key = f"{alert_type}:{identifier}"
        self._last_alerts[key] = datetime.now()
    
    def send_if_allowed(
        self,
        alert_type: str,
        send_func: callable,
        identifier: str = "",
        **kwargs
    ) -> bool:
        """
        Send alert if not in cooldown period.
        
        Args:
            alert_type: Type of alert
            send_func: Function to call to send the alert
            identifier: Unique identifier for deduplication
            **kwargs: Arguments to pass to send_func
        """
        if not self.can_send_alert(alert_type, identifier):
            logger.info(f"Alert {alert_type}:{identifier} in cooldown, skipping")
            return False
        
        result = send_func(**kwargs)
        if result:
            self.mark_alert_sent(alert_type, identifier)
        return result


# Global alert manager instance
alert_manager = AlertManager()


# ============================================
# Convenience functions with rate limiting
# ============================================

def send_high_error_rate_alert(
    total_companies: int,
    failed_companies: int,
    error_messages: List[str],
    log_file: str = None
) -> bool:
    """Send high error rate alert with rate limiting."""
    return alert_manager.send_if_allowed(
        AlertType.HIGH_ERROR_RATE,
        alert_high_error_rate,
        identifier="global",
        total_companies=total_companies,
        failed_companies=failed_companies,
        error_messages=error_messages,
        log_file=log_file
    )


def send_company_failures_alert(failed_companies: List[Dict[str, Any]]) -> bool:
    """Send company failures alert with rate limiting."""
    return alert_manager.send_if_allowed(
        AlertType.COMPANY_FAILURES,
        alert_company_failures,
        identifier="global",
        failed_companies=failed_companies
    )


def send_scraper_crash_alert(
    error_message: str,
    stack_trace: str = None,
    context: Dict[str, Any] = None
) -> bool:
    """Send scraper crash alert (no rate limiting for crashes)."""
    return alert_scraper_crash(error_message, stack_trace, context)


if __name__ == "__main__":
    # Test the alerting system
    logging.basicConfig(level=logging.INFO)
    
    print("Testing alert system...")
    
    # Test high error rate alert
    result = alert_high_error_rate(
        total_companies=100,
        failed_companies=25,
        error_messages=["Test error 1", "Test error 2"],
        log_file="test.log"
    )
    print(f"High error rate alert: {'Sent' if result else 'Failed/Skipped'}")
