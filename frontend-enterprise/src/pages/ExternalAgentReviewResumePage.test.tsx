// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

const apiGet = vi.fn();

vi.mock('@/api/client', () => ({
  api: { get: (...args: unknown[]) => apiGet(...args) },
}));

import ExternalAgentReviewResumePage from './ExternalAgentReviewResumePage';

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
}

afterEach(() => {
  cleanup();
  apiGet.mockReset();
});

describe('external Agent review recovery', () => {
  it('resolves the connection to its enrollment and restores the workflow URL', async () => {
    apiGet.mockResolvedValue({
      id: 'enrollment_restore_1',
      connectionId: 'externalagent_restore_1',
      workflowStage: 'manifest_pending_review',
    });

    render(
      <MemoryRouter initialEntries={['/enterprise/agents/external/externalagent_restore_1/review']}>
        <Routes>
          <Route path="/enterprise/agents/external/:connectionId/review" element={<ExternalAgentReviewResumePage />} />
          <Route path="/enterprise/agents/external/connect" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toBe('/enterprise/agents/external/connect?enrollmentId=enrollment_restore_1');
    });
    expect(apiGet).toHaveBeenCalledWith('/api/enterprise/external-agents/externalagent_restore_1/enrollment');
  });

  it('offers a retry instead of silently creating a duplicate enrollment', async () => {
    apiGet.mockRejectedValue(new Error('未找到可恢复的配对记录'));

    render(
      <MemoryRouter initialEntries={['/enterprise/agents/external/externalagent_missing/review']}>
        <Routes><Route path="/enterprise/agents/external/:connectionId/review" element={<ExternalAgentReviewResumePage />} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole('heading', { name: '无法恢复审核' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /重新加载/ })).toBeTruthy();
    expect(apiGet).toHaveBeenCalledTimes(1);
  });
});
