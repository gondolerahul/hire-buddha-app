# Phase 4 - Frontend Campaign Builder

## Overview

Phase 4 provides a user-friendly interface for creating and managing bulk voice calling campaigns.

## Backend ✅ COMPLETE

### Components Created:

1. **`campaign_models.py`**
   - `Campaign` model (name, status, contacts, scheduling, throttling)
   - `CampaignCall` model (individual call tracking)

2. **`campaign_service.py`**
   - Campaign CRUD operations
   - CSV parsing and validation
   - Status tracking and metrics
   - Active call monitoring

3. **`campaign_router.py`**
   - `POST /api/v1/campaigns` - Create campaign
   - `POST /api/v1/campaigns/upload-csv` - Upload contact list
   - `GET /api/v1/campaigns` - List campaigns
   - `GET /api/v1/campaigns/{id}` - Get campaign details
   - `GET /api/v1/campaigns/{id}/status` - Real-time status
   - `GET /api/v1/campaigns/{id}/active-calls` - Live calls
   - `PATCH /api/v1/campaigns/{id}/status` - Start/pause/stop

4. **Migration**: `b2c3d4e5f6a7_add_campaign_tables.py`

###Database Schema:

**campaigns table**:
- Campaign metadata (name, description)
- Contact list (JSONB array)
- Agent configuration
- Scheduling (start/end times)
- Throttling (max concurrent, calls per hour)
- Status tracking (initiated, completed, failed)
- Outcome distribution

**campaign_calls table**:
- Individual call records
- Contact data
- Call status and outcome
- Timing (scheduled, called, completed)
- Retry tracking

## Frontend Components (To Be Built)

### 1. CampaignList Component

**Location**: `frontend/src/pages/campaigns/CampaignList.tsx`

**Features**:
- Table view of all campaigns
- Status badges (draft, running, completed)
- Quick metrics (total contacts, completed, failed)
- Actions (view, start, pause, delete)
- Filter by status
- Pagination

**API Calls**:
```typescript
GET /api/v1/campaigns?status={status}&limit=50&offset=0
```

### 2. CreateCampaign Component

**Location**: `frontend/src/pages/campaigns/CreateCampaign.tsx`

**Form Fields**:
- Campaign name (required)
- Description (optional)
- Agent selector (dropdown from hierarchical_entities)
- Provider selector (Twilio / Tata Tele)
- CSV upload for contacts
- Scheduling (start/end datetime)
- Throttling (max concurrent calls, calls/hour)

**Features**:
- CSV upload with drag-and-drop
- Live CSV validation and preview
- Error display (missing fields, invalid phones)
- Agent search/filter
- Save as draft or schedule immediately

**API Calls**:
```typescript
POST /api/v1/campaigns/upload-csv (FormData with file)
POST /api/v1/campaigns (campaign data)
```

### 3. CampaignDetails Component

**Location**: `frontend/src/pages/campaigns/CampaignDetails.tsx`

**Sections**:
- **Campaign Info**: Name, status, agent, provider
- **Metrics Dashboard**:
  - Progress bar (completed / total)
  - Pie chart (outcomes: success, no_answer, failed, busy)
  - Real-time stats (calling, pending, completed)
- **Live Call Monitor**:
  - Table of active calls
  - Contact name, phone, duration
  - Auto-refresh every 5 seconds
- **Contact List**:
  - Searchable/filterable table
  - Call status per contact
  - Retry count
- **Actions**:
  - Start campaign
  - Pause/Resume
  - Stop (cancel remaining)
  - Export results

**API Calls**:
```typescript
GET /api/v1/campaigns/{id}
GET /api/v1/campaigns/{id}/status (polling every 5s)
GET /api/v1/campaigns/{id}/active-calls (polling every 5s)
PATCH /api/v1/campaigns/{id}/status
```

### 4. CSVUploader Component

**Location**: `frontend/src/components/campaigns/CSVUploader.tsx`

**Features**:
- Drag-and-drop zone
- File picker fallback
- Upload progress
- Parsing and validation
- Preview table (first 10 contacts)
- Error list with row numbers
- Download sample CSV template

**Validation**:
- Required field: `phone`
- Optional fields: `name`, `email`, custom fields
- Phone format: Must start with `+` (country code)
- Max file size: 5MB
- Max contacts: 10,000

**Sample CSV**:
```csv
phone,name,email,custom_field
+14155551234,John Doe,john@example.com,VIP
+919876543210,Jane Smith,jane@example.com,Regular
```

## Routing

Update `frontend/src/router/index.tsx`:

```typescript
{
  path: '/campaigns',
  element: <CampaignList />,
},
{
  path: '/campaigns/new',
  element: <CreateCampaign />,
},
{
  path: '/campaigns/:id',
  element: <CampaignDetails />,
}
```

## Sidebar Navigation

Add to sidebar menu:

```typescript
{
  icon: <PhoneIcon />,
  label: 'Campaigns',
  path: '/campaigns',
  badge: activeCampaignsCount // optional
}
```

## State Management

Use React hooks for local state:

```typescript
// Campaign list
const [campaigns, setCampaigns] = useState([]);
const [loading, setLoading] = useState(false);
const [filters, setFilters] = useState({ status: null });

// Create campaign
const [formData, setFormData] = useState({...});
const [contacts, setContacts] = useState([]);
const [validationErrors, setValidationErrors] = useState([]);

// Campaign details
const [campaign, setCampaign] = useState(null);
const [metrics, setMetrics] = useState({});
const [activeCalls, setActiveCalls] = useState([]);
```

## Styling Guidelines

**Use existing design system**:
- GlassCard for main containers
- Button variants (primary, secondary, danger)
- StatusBadge for campaign status
- ProgressBar for completion tracking
- DataTable for lists

**Color scheme**:
- Draft: Gray
- Scheduled: Blue
- Running: Green (pulsing animation)
- Paused: Orange
- Completed: Purple
- Failed: Red

## API Integration

Create API service: `frontend/src/api/campaigns.ts`

```typescript
export const campaignsAPI = {
  list: (params) => api.get('/campaigns', { params }),
  create: (data) => api.post('/campaigns', data),
  get: (id) => api.get(`/campaigns/${id}`),
  getStatus: (id) => api.get(`/campaigns/${id}/status`),
  getActiveCalls: (id) => api.get(`/campaigns/${id}/active-calls`),
  updateStatus: (id, status) => api.patch(`/campaigns/${id}/status`, { status }),
  uploadCSV: (file) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/campaigns/upload-csv', formData);
  }
};
```

## Testing Checklist

### Backend:
- [ ] Run migration: `alembic upgrade head`
- [ ] Test CSV upload endpoint
- [ ] Test campaign creation
- [ ] Test campaign listing
- [ ] Test status updates

### Frontend:
- [ ] Upload CSV with valid contacts
- [ ] Upload CSV with errors (verify error display)
- [ ] Create campaign with all fields
- [ ] View campaign list
- [ ] View campaign details
- [ ] Start campaign (verify status change)
- [ ] Monitor live calls (verify auto-refresh)
- [ ] Pause/Resume campaign
- [ ] Stop campaign

## Sample CSV for Testing

Create `sample_contacts.csv`:

```csv
phone,name,email,notes
+14155551001,Alice Johnson,alice@example.com,High priority customer
+14155551002,Bob Smith,bob@example.com,Follow-up required
+919876543001,Charlie Brown,charlie@example.com,VIP client
+919876543002,Diana Prince,diana@example.com,New lead
+442071234567,Eve Williams,eve@example.com,London office
```

## Implementation Priority

1. **Backend (✅ DONE)**
   - Models, service, router, migration

2. **API Integration**
   - Create `campaigns.ts` API service

3. **Basic UI**
   - CampaignList (read-only)
   - CSV upload component

4. **Create Flow**
   - CreateCampaign form
   - CSV validation
   - Agent selector

5. **Details View**
   - Metrics dashboard
   - Live call monitor
   - Control buttons

6. **Polish**
   - Real-time updates (WebSocket or polling)
   - Export functionality
   - Better error handling

## Next Phase

Once UI is complete, **Phase 5** will add:
- Campaign execution engine (auto-dialer)
- Real-time monitoring dashboard
- Detailed analytics and reporting
- Call recording playback
- Transcript viewer
