// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../components/AppHeader', () => ({ default: () => <header /> }));
vi.mock('../components/BrandLogo', () => ({ default: () => <span>开工吧</span> }));

import LoginPage from './LoginPage';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('LoginPage phone authentication', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it('reveals the password only after SMS verification and then signs in', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ sms_login_enabled: true }))
      .mockResolvedValueOnce(jsonResponse({ message: '已发送', retry_after_seconds: 60, debug_code: '123456' }))
      .mockResolvedValueOnce(jsonResponse({ verification_token: 'verified-token', expires_in_seconds: 240 }))
      .mockResolvedValueOnce(jsonResponse({
        token: 'session-token',
        user: {
          id: 'user_phone',
          tenant_id: 'tenant_demo',
          username: 'phone-user',
          role: 'member',
          phone_masked: '138****8000',
        },
      }));
    vi.stubGlobal('fetch', fetchMock);
    const onLogin = vi.fn();
    const user = userEvent.setup();
    render(<LoginPage onLogin={onLogin} />);

    await user.click(await screen.findByRole('button', { name: '手机号登录' }));
    expect(screen.queryByLabelText('密码')).toBeNull();
    await user.type(screen.getByLabelText('手机号'), '13800138000');
    await user.click(screen.getByRole('button', { name: '获取验证码' }));

    expect(await screen.findByText('开发环境验证码：123456')).not.toBeNull();
    expect(screen.queryByLabelText('密码')).toBeNull();
    await user.type(screen.getByLabelText('短信验证码'), '123456');
    await user.click(screen.getByRole('button', { name: '验证手机号' }));

    expect(await screen.findByText('手机号验证成功，请输入密码')).not.toBeNull();
    await user.type(screen.getByLabelText('密码'), 'OldPassword1');
    await user.click(screen.getByRole('button', { name: '登录' }));

    await waitFor(() => expect(onLogin).toHaveBeenCalledWith(expect.objectContaining({ token: 'session-token' })));
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      '/api/auth/phone-login',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('uses a separate reset verification and accepts a confirmed new password', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ sms_login_enabled: true }))
      .mockResolvedValueOnce(jsonResponse({ message: '已发送', retry_after_seconds: 60, debug_code: '654321' }))
      .mockResolvedValueOnce(jsonResponse({ verification_token: 'reset-token', expires_in_seconds: 240 }))
      .mockResolvedValueOnce(jsonResponse({
        token: 'new-session-token',
        user: { id: 'user_phone', tenant_id: 'tenant_demo', username: 'phone-user', role: 'member' },
      }));
    vi.stubGlobal('fetch', fetchMock);
    const onLogin = vi.fn();
    const user = userEvent.setup();
    render(<LoginPage onLogin={onLogin} />);

    await user.click(await screen.findByRole('button', { name: '手机号登录' }));
    await user.click(screen.getByRole('button', { name: '忘记密码' }));
    await user.type(screen.getByLabelText('手机号'), '13800138000');
    await user.click(screen.getByRole('button', { name: '获取验证码' }));
    await user.type(await screen.findByLabelText('短信验证码'), '654321');
    await user.click(screen.getByRole('button', { name: '验证手机号' }));
    await user.type(await screen.findByLabelText('密码'), 'NewPassword2!');
    await user.type(screen.getByLabelText('确认新密码'), 'NewPassword2!');
    await user.click(screen.getByRole('button', { name: '重置密码并登录' }));

    await waitFor(() => expect(onLogin).toHaveBeenCalled());
    const resetRequest = JSON.parse(fetchMock.mock.calls[3][1].body as string);
    expect(resetRequest).toMatchObject({
      new_password: 'NewPassword2!',
      verification_token: 'reset-token',
    });
    const sendRequest = JSON.parse(fetchMock.mock.calls[1][1].body as string);
    expect(sendRequest.purpose).toBe('reset_password');
  });

  it('keeps account login as the safe production fallback when SMS is unavailable', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ sms_login_enabled: false }))
      .mockResolvedValueOnce(jsonResponse({
        token: 'account-session',
        user: { id: 'user_admin', tenant_id: 'tenant_demo', username: 'admin', role: 'admin' },
      }));
    vi.stubGlobal('fetch', fetchMock);
    const onLogin = vi.fn();
    const user = userEvent.setup();
    render(<LoginPage onLogin={onLogin} />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/auth/capabilities', expect.anything()));
    await user.click(screen.getByRole('button', { name: '登录' }));
    expect(screen.queryByRole('button', { name: '返回手机号登录' })).toBeNull();
    await user.type(screen.getByLabelText('账号'), 'admin');
    await user.type(screen.getByLabelText('密码'), 'admin');
    await user.click(screen.getByRole('button', { name: '登录' }));

    await waitFor(() => expect(onLogin).toHaveBeenCalledWith(expect.objectContaining({ token: 'account-session' })));
  });
});
