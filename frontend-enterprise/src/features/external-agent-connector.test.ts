import { describe, expect, it } from 'vitest';
import {
  CONNECTOR_INSTALL_COMMAND,
  CONNECTOR_REF,
  CONNECTOR_REF_IS_PINNED,
  CONNECTOR_REPOSITORY,
  connectorCommands,
  externalAgentNeedsSetup,
  externalAgentReviewPath,
} from './external-agent-connector';

describe('external Agent connector release and routing contract', () => {
  it('installs exclusively from the independent connector repository', () => {
    expect(CONNECTOR_REPOSITORY).toBe('KaiGongBa/kaigongba-agent-connector');
    expect(CONNECTOR_INSTALL_COMMAND).toContain('kaigongba-agent-connector.git@');
    expect(CONNECTOR_INSTALL_COMMAND).not.toContain('KaiGongBa/kaigongba.git');
    expect(CONNECTOR_INSTALL_COMMAND).not.toContain('subdirectory=sdk/python');
    expect(CONNECTOR_REF).toBe('v0.7.0');
    expect(CONNECTOR_REF_IS_PINNED).toBe(true);
  });

  it('never places the one-time pairing code in process arguments', () => {
    const commands = connectorCommands({
      baseUrl: 'https://app.kaigongba.net',
      enrollmentId: 'enrollment_resume_1',
      transport: 'polling',
    });

    expect(commands.discoverPreview).toContain('kaigongba-agent discover preview');
    expect(commands.discoverPreview).toContain('--approved-root /path/to/approved-skills');
    expect(commands.discoverPreview).toContain('--agent-description');
    expect(commands.discoverConfirm).toContain('kaigongba-agent discover confirm');
    expect(commands.discoverConfirm).toContain('--digest sha256:reviewed-preview-digest');
    expect(commands.enroll).toContain('kaigongba-agent register enroll');
    expect(commands.enroll).not.toContain('pairing-code');
    expect(commands.enroll).not.toContain('一次性码');
    expect(Object.values(commands).join('\n')).not.toContain('PAIR-ONLY-ONCE');
    expect(commands.manifest).toContain('register manifest');
    expect(commands.manifest).toContain('--manifest /path/to/manifest-confirmed.json');
  });

  it('keeps pending connections on the resumable review path', () => {
    expect(externalAgentReviewPath('externalagent/a')).toBe('/enterprise/agents/external/externalagent%2Fa/review');
    expect(externalAgentNeedsSetup('manifest_pending_review')).toBe(true);
    expect(externalAgentNeedsSetup('draft_pending_confirmation')).toBe(true);
    expect(externalAgentNeedsSetup('available')).toBe(false);
    expect(externalAgentNeedsSetup('disconnected')).toBe(false);
  });
});
