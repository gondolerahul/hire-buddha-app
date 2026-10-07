# Tenants Endpoint 404 Error - Fixed

## Error
```
GET http://34.100.230.121:8000/api/v1/tenants 404 (Not Found)
```

## Root Cause
The frontend was calling `/api/v1/tenants` but the actual endpoint is `/api/v1/companies/tenants`.

### Why?
The `company_router` in the backend has:
```python
router = APIRouter(prefix="/companies", tags=["companies"])

@router.get("/tenants", response_model=List[CompanyResponse])
async def get_tenants(...):
    ...
```

And it's included in main.py as:
```python
app.include_router(company_router, prefix="/api/v1")
```

So the full path is: `/api/v1` + `/companies` + `/tenants` = **`/api/v1/companies/tenants`**

## Solution
Updated the frontend to use the correct endpoint path.

**File**: `/frontend/src/pages/streaming/PhoneNumbersPage.tsx`

**Before**:
```typescript
const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}/tenants`, {
```

**After**:
```typescript
const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}/companies/tenants`, {
```

## Testing
1. **Refresh your browser** (Ctrl+F5)
2. Open DevTools Console (F12)
3. Navigate to Phone Numbers page
4. Click "Add Phone Number"
5. Check console for:
   - **If you have admin role**: `Loaded X customers from tenants`
   - **If you don't have admin role**: `Failed to fetch customers: 403 Forbidden` (expected)

## Expected Behavior

### For App Admin or Partner Admin Users
- Dropdown will populate with tenants
- Console shows: `Loaded X customers from tenants`
- Can select from dropdown OR enter new customer name

### For Regular Users
- No dropdown (403 Forbidden is expected)
- Console shows: `User does not have permission to view tenants`
- Can enter customer name manually in text field
- Form still works perfectly!

## Status
✅ **FIXED** - Correct endpoint path is now being used
