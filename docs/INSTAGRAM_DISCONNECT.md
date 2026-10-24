# Instagram Disconnect Feature

## Overview
Allows users to securely disconnect their Instagram Professional account from ContentMind. This revokes stored access tokens, updates the connection status, and immediately stops sync jobs.

## Backend Implementation

### Endpoint
```
DELETE /api/instagram/connections/{connection_id}
```

### Response
```json
{"status": "disconnected"}
```

### Service Logic (`backend/app/services/instagram_service.py:388-397`)
```python
def disconnect_connection(self, connection_id: int) -> bool:
    """Disconnect (soft delete) an Instagram connection."""
    conn = self.get_connection(connection_id)
    if not conn:
        return False
    conn.status = "disconnected"
    conn.access_token_encrypted = ""
    conn.updated_at = datetime.now(timezone.utc)
    self.db.commit()
    return True
```

### Changes Made
- **Status**: Set `status` to `"disconnected"` (soft delete, not hard delete)
- **Token Wipe**: `access_token_encrypted` cleared to `""`
- **Timestamp**: `updated_at` set to current UTC time
- **Commit**: Database session committed

### Tenant Isolation
- Connection lookup includes user scoping: `self.get_connection(connection_id)` checks ownership
- Only the owning user can disconnect their own connection
- Unauthorized connection IDs return 404

## Frontend Implementation

### Instagram Page (`frontend/src/pages/Instagram.tsx:162-178`)
```typescript
const handleDisconnect = useCallback(async () => {
    if (!selectedConnection) return
    if (!window.confirm(`Disconnect @${selectedConnection.username}? This will remove stored tokens and stop syncs.`)) {
      return
    }
    try {
      await api.delete(`/instagram/connections/${selectedConnection.id}`)
      setNotice(`Disconnected @${selectedConnection.username}`)
      setSelectedConnection(null)
      setPosts([])
      setSyncJobs([])
      setInsights(null)
      await loadConnections()
    } catch (e) {
      setError(apiErrorMessage(e))
    }
  }, [selectedConnection, loadConnections])
```

### UI Behavior
- **Confirmation dialog**: `window.confirm()` with username in message
- **Token removal**: API call clears encrypted token in backend
- **State update**: Selected connection reset, posts/sync jobs/insights cleared
- **Connection list refresh**: `loadConnections()` refetches remaining connections
- **Visual feedback**: Success notice shown, UI updates to "No Instagram accounts connected"

### Connected Account Card
- Each connected account card has a "Disconnect" button (btn btn-ghost text-error-600)
- On click: confirmation → API delete → immediate UI reset → reload connections
- Last remaining connection: UI shows empty state with "Connect Instagram" CTA

## Test Coverage

| Test Scenario | Expected Behavior |
|---|---|
| Successful disconnect | Status → "disconnected", token cleared, UI resets |
| Repeated disconnect | Idempotent — second call does not error |
| No connections | 404 status (or graceful handling) |
| Disconnect non-existent | 404 response |
| Disconnect other tenant's | 404 (tenant isolation) |

## Provenance & Demo Mode
- Disconnect action clearly labeled as user-initiated
- No real token revocation against Meta API in demo mode
- UI shows "Disconnected" status badge with informational note
- Demo data never presented as actual Instagram results
- Demo mode verified without requiring a real Instagram account
- Mock external API calls in automated tests; real-account test documented separately