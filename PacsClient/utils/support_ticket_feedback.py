"""Receipt-driven plain UI feedback; no descriptions, logs or untrusted exception text."""
from uuid import UUID


def ticket_feedback(result):
    state = result.get('state')
    if state == 'received' and result.get('ticket_submitted'):
        try:
            identifier = str(UUID(result['issue_id']))
        except (KeyError, TypeError, ValueError, AttributeError):
            return 'Failed', 'Support delivery could not be verified. No success is confirmed.'
        return 'Done', f'Your Help Ticket was received by AI-PACS support. Ticket ID: {identifier}.'
    if state == 'running':
        done, total = result.get('completed_chunks'), result.get('total_chunks')
        if type(done) is int and type(total) is int and 0 <= done <= total <= 342:
            return 'Working: Sending Help Ticket', f'Sending Help Ticket: {done} of {total} parts received. Waiting for the final support receipt.'
        return 'Working: Sending Help Ticket', 'Preparing and sending your Help Ticket. Waiting for the support receipt.'
    if state == 'pending' and result.get('restored'):
        return 'Confirmation required', 'I found your previous unsent Help Ticket. Review the restored report, confirm consent, and click Retry pending issue. This sends the same request without creating a duplicate.'
    if state == 'not_found':
        return 'Ready', 'No saved pending Help Ticket or confirmed receipt was found for this linked account. No new ticket was sent.'
    messages = {
        'WEBSITE_ACCOUNT_REQUIRED':'Link your AI-PACS website account in Settings before sending.',
        'WEBSITE_SESSION_EXPIRED':'Your website session expired. Reconnect the linked website account before retrying.',
        'WEBSITE_PAIRING_REVOKED':'The website pairing was revoked. Reconnect the intended website account.',
        'SUPPORT_ENDPOINT_UNAVAILABLE':'The website does not support this upload protocol. The request is saved locally.',
        'ISSUE_REJECTED':'The website rejected the ticket format or size. The request is saved locally.',
        'ISSUE_CONTENT_CONFLICT':'The website found different content for the same request. The saved request has not been replaced.',
        'RATE_LIMITED':'The website upload limit was reached. The request is saved locally; retry later.',
    }
    text = messages.get(result.get('error_code'))
    if text:
        return 'Failed', text + ' Successful delivery is not confirmed.'
    if state == 'pending':
        return 'Failed', 'Support delivery is not confirmed. Your ticket remains saved locally. Retry pending issue continues the same request.'
    return 'Failed', 'The Help Ticket operation did not complete. No successful delivery is confirmed.'
