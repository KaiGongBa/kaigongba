import { useEffect, useState } from 'react';

import { api, TENANT_ID } from '../api/client';
import { setEnterpriseAuthSession, type EnterpriseAuthSession } from '../auth';
import AppHeader from '../components/AppHeader';
import BrandLogo from '../components/BrandLogo';
import IconFieldClear from '../assets/icons/field-clear.svg?react';
import IconFieldEye from '../assets/icons/field-eye.svg?react';
import IconFieldEyeOn from '../assets/icons/field-eye-on.svg?react';
import loginPreview from '../assets/brand/kaigongba-product-preview-v2.png';

export type LoginPageProps = {
  onLogin: (session: EnterpriseAuthSession) => void;
};

type Screen = 'phone-login' | 'reset-password' | 'account-login';
type PhoneStep = 'phone' | 'code' | 'password';
type SmsPurpose = 'login' | 'reset_password';

type SmsSendResponse = {
  message: string;
  retry_after_seconds: number;
  debug_code?: string;
};

type SmsVerifyResponse = {
  verification_token: string;
  expires_in_seconds: number;
};

type AuthCapabilitiesResponse = {
  sms_login_enabled: boolean;
};

const PHONE_PATTERN = /^1[3-9]\d{9}$/;

export default function LoginPage({ onLogin }: LoginPageProps) {
  const [showForm, setShowForm] = useState(false);
  const [screen, setScreen] = useState<Screen>('account-login');
  const [smsLoginEnabled, setSmsLoginEnabled] = useState(false);
  const [phoneStep, setPhoneStep] = useState<PhoneStep>('phone');
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [verificationToken, setVerificationToken] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [debugCode, setDebugCode] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [username, setUsername] = useState('');

  useEffect(() => {
    let active = true;
    void api.get<AuthCapabilitiesResponse>('/api/auth/capabilities')
      .then((result) => {
        if (!active) return;
        setSmsLoginEnabled(result.sms_login_enabled);
        if (result.sms_login_enabled) setScreen('phone-login');
      })
      .catch(() => {
        if (!active) return;
        setSmsLoginEnabled(false);
        setScreen('account-login');
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setTimeout(() => setCooldown((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [cooldown]);

  const purpose: SmsPurpose = screen === 'reset-password' ? 'reset_password' : 'login';

  function switchScreen(next: Screen, keepPhone = false) {
    setScreen(next);
    setPhoneStep('phone');
    if (!keepPhone) setPhone('');
    setCode('');
    setVerificationToken('');
    setPassword('');
    setConfirmPassword('');
    setShowPassword(false);
    setDebugCode('');
    setError('');
  }

  function normalizedPhone() {
    return phone.replace(/\D/g, '').slice(0, 11);
  }

  async function sendCode() {
    const mobile = normalizedPhone();
    if (!PHONE_PATTERN.test(mobile)) {
      setError('请输入正确的 11 位手机号');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const result = await api.post<SmsSendResponse>('/api/auth/sms/send', {
        tenant_id: TENANT_ID,
        phone: mobile,
        purpose,
      });
      setPhone(mobile);
      setPhoneStep('code');
      setCooldown(result.retry_after_seconds || 60);
      setDebugCode(result.debug_code || '');
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '验证码发送失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }

  async function verifyCode() {
    if (!/^\d{6}$/.test(code)) {
      setError('请输入 6 位短信验证码');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const result = await api.post<SmsVerifyResponse>('/api/auth/sms/verify', {
        tenant_id: TENANT_ID,
        phone: normalizedPhone(),
        purpose,
        code,
      });
      setVerificationToken(result.verification_token);
      setPhoneStep('password');
      setDebugCode('');
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '验证码校验失败');
    } finally {
      setLoading(false);
    }
  }

  async function finishPhoneFlow() {
    if (!password) {
      setError(screen === 'reset-password' ? '请输入新密码' : '请输入密码');
      return;
    }
    if (screen === 'reset-password') {
      if (password.length < 8 || password.length > 64) {
        setError('新密码需为 8–64 个字符');
        return;
      }
      const categoryCount = [/[A-Za-z]/.test(password), /\d/.test(password), /[^A-Za-z\d]/.test(password)]
        .filter(Boolean).length;
      if (categoryCount < 2) {
        setError('新密码需至少包含字母、数字或符号中的两类');
        return;
      }
      if (password !== confirmPassword) {
        setError('两次输入的密码不一致');
        return;
      }
    }

    setLoading(true);
    setError('');
    try {
      const endpoint = screen === 'reset-password' ? '/api/auth/password/reset' : '/api/auth/phone-login';
      const body = screen === 'reset-password'
        ? {
            tenant_id: TENANT_ID,
            phone: normalizedPhone(),
            new_password: password,
            verification_token: verificationToken,
          }
        : {
            tenant_id: TENANT_ID,
            phone: normalizedPhone(),
            password,
            verification_token: verificationToken,
          };
      const session = await api.post<EnterpriseAuthSession>(endpoint, body);
      completeLogin(session);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '操作失败，请重试');
    } finally {
      setLoading(false);
    }
  }

  async function accountLogin() {
    if (!username.trim() || !password) {
      setError('请输入账号和密码');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const session = await api.post<EnterpriseAuthSession>('/api/auth/login', {
        tenant_id: TENANT_ID,
        username: username.trim(),
        password,
      });
      completeLogin(session);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '账号或密码错误');
    } finally {
      setLoading(false);
    }
  }

  function completeLogin(session: EnterpriseAuthSession) {
    setEnterpriseAuthSession(session);
    onLogin(session);
  }

  const inputClass =
    'flex h-[44px] w-full items-center gap-[8px] rounded-[10px] border bg-white px-[16px] transition-colors focus-within:border-[#18181a]';

  return (
    <div className="relative flex min-h-screen flex-col bg-white">
      <AppHeader className="h-[60px] shrink-0 px-[32px]" left={<BrandLogo markSize={28} />} right={null} />

      <main className="flex flex-1 flex-col items-center px-[20px] sm:px-[32px]">
        <div className="flex flex-col items-center pt-[60px]">
          <span className="flex items-center justify-center rounded-[10px] border-[0.5px] border-[#e3e7f1] bg-[#f6f6f6] px-[20px] py-[6px] text-[14px] text-[#464c5e]">
            我们来做什么？
          </span>
          <h1 className="mt-[6px] text-center text-[42px] font-semibold leading-[1.35] tracking-[1.08px] text-[#18181a] sm:text-[54px] sm:leading-[80px]">
            开工吧
            <br />
            数字员工运营平台
          </h1>

          {!showForm ? (
            <button
              type="button"
              onClick={() => setShowForm(true)}
              className="mt-[24px] flex items-center justify-center rounded-[10px] bg-[#18181a] px-[36px] py-[10px] text-[16px] text-white transition-colors hover:bg-[#18181a]/90"
            >
              {smsLoginEnabled ? '手机号登录' : '登录'}
            </button>
          ) : (
            <section className="mt-[24px] w-full max-w-[360px] duration-300 ease-out animate-in fade-in slide-in-from-top-4">
              {screen === 'account-login' ? (
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    void accountLogin();
                  }}
                  className="flex flex-col"
                >
                  <FormHeading title="账号密码登录" description="供尚未绑定手机号的现有账号使用" />
                  <div className={`${inputClass} ${error ? 'border-[#f54a45]' : 'border-[#e3e7f1]'}`}>
                    <input
                      value={username}
                      autoComplete="username"
                      placeholder="请输入账号"
                      aria-label="账号"
                      onChange={(event) => {
                        setUsername(event.target.value);
                        setError('');
                      }}
                      className="min-w-0 flex-1 border-0 bg-transparent text-[14px] text-[#18181a] outline-none placeholder:text-[#757f9c]"
                    />
                    {username && <ClearButton label="清空账号" onClick={() => setUsername('')} />}
                  </div>
                  <PasswordField
                    className="mt-[12px]"
                    value={password}
                    show={showPassword}
                    placeholder="请输入密码"
                    onChange={(value) => {
                      setPassword(value);
                      setError('');
                    }}
                    onToggle={() => setShowPassword((value) => !value)}
                  />
                  <ErrorMessage message={error} />
                  <PrimaryButton loading={loading} text="登录" loadingText="登录中…" />
                  {smsLoginEnabled && (
                    <TextButton onClick={() => switchScreen('phone-login')}>返回手机号登录</TextButton>
                  )}
                </form>
              ) : (
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (phoneStep === 'phone') void sendCode();
                    else if (phoneStep === 'code') void verifyCode();
                    else void finishPhoneFlow();
                  }}
                  className="flex flex-col"
                >
                  <FormHeading
                    title={screen === 'reset-password' ? '找回密码' : '手机号登录'}
                    description={stepDescription(screen, phoneStep, phone)}
                  />

                  {phoneStep === 'phone' && (
                    <div className={`${inputClass} ${error ? 'border-[#f54a45]' : 'border-[#e3e7f1]'}`}>
                      <span className="shrink-0 border-r border-[#e3e7f1] pr-[10px] text-[14px] text-[#464c5e]">+86</span>
                      <input
                        value={phone}
                        inputMode="numeric"
                        autoComplete="tel"
                        placeholder="请输入手机号"
                        aria-label="手机号"
                        onChange={(event) => {
                          setPhone(event.target.value.replace(/\D/g, '').slice(0, 11));
                          setError('');
                        }}
                        className="min-w-0 flex-1 border-0 bg-transparent text-[14px] text-[#18181a] outline-none placeholder:text-[#757f9c]"
                      />
                      {phone && <ClearButton label="清空手机号" onClick={() => setPhone('')} />}
                    </div>
                  )}

                  {phoneStep === 'code' && (
                    <>
                      <div className={`${inputClass} ${error ? 'border-[#f54a45]' : 'border-[#e3e7f1]'}`}>
                        <input
                          value={code}
                          inputMode="numeric"
                          autoComplete="one-time-code"
                          placeholder="请输入 6 位验证码"
                          aria-label="短信验证码"
                          onChange={(event) => {
                            setCode(event.target.value.replace(/\D/g, '').slice(0, 6));
                            setError('');
                          }}
                          className="min-w-0 flex-1 border-0 bg-transparent text-[18px] tracking-[6px] text-[#18181a] outline-none placeholder:text-[14px] placeholder:tracking-normal placeholder:text-[#757f9c]"
                        />
                        <button
                          type="button"
                          disabled={cooldown > 0 || loading}
                          onClick={() => void sendCode()}
                          className="shrink-0 text-[12px] text-[#1a71ff] disabled:text-[#a8afc0]"
                        >
                          {cooldown > 0 ? `${cooldown} 秒后重发` : '重新发送'}
                        </button>
                      </div>
                      {debugCode && (
                        <p className="mt-[8px] rounded-[8px] bg-[#f2f6ff] px-[10px] py-[7px] text-[12px] text-[#3667b3]">
                          开发环境验证码：{debugCode}
                        </p>
                      )}
                    </>
                  )}

                  {phoneStep === 'password' && (
                    <>
                      <PasswordField
                        value={password}
                        show={showPassword}
                        autoComplete={screen === 'reset-password' ? 'new-password' : 'current-password'}
                        placeholder={screen === 'reset-password' ? '设置 8–64 位新密码' : '请输入密码'}
                        onChange={(value) => {
                          setPassword(value);
                          setError('');
                        }}
                        onToggle={() => setShowPassword((value) => !value)}
                      />
                      {screen === 'reset-password' && (
                        <PasswordField
                          className="mt-[12px]"
                          value={confirmPassword}
                          show={showPassword}
                          autoComplete="new-password"
                          placeholder="再次输入新密码"
                          ariaLabel="确认新密码"
                          onChange={(value) => {
                            setConfirmPassword(value);
                            setError('');
                          }}
                          onToggle={() => setShowPassword((value) => !value)}
                        />
                      )}
                    </>
                  )}

                  <ErrorMessage message={error} />
                  <PrimaryButton
                    loading={loading}
                    text={phoneStep === 'phone' ? '获取验证码' : phoneStep === 'code' ? '验证手机号' : screen === 'reset-password' ? '重置密码并登录' : '登录'}
                    loadingText={phoneStep === 'phone' ? '发送中…' : phoneStep === 'code' ? '验证中…' : '提交中…'}
                  />

                  {phoneStep !== 'phone' && (
                    <TextButton onClick={() => switchScreen(screen, true)}>更换手机号</TextButton>
                  )}
                  {screen === 'phone-login' && phoneStep === 'password' && (
                    <TextButton onClick={() => switchScreen('reset-password', true)}>忘记密码？短信验证后找回</TextButton>
                  )}
                  {screen === 'phone-login' && phoneStep === 'phone' && (
                    <TextButton onClick={() => switchScreen('reset-password')}>忘记密码</TextButton>
                  )}
                  {screen === 'reset-password' && (
                    <TextButton onClick={() => switchScreen('phone-login', true)}>返回手机号登录</TextButton>
                  )}
                  {screen === 'phone-login' && phoneStep === 'phone' && (
                    <TextButton onClick={() => switchScreen('account-login')}>使用账号密码登录</TextButton>
                  )}
                </form>
              )}
            </section>
          )}
        </div>

        <div className="mt-[32px] flex w-full justify-center">
          <img
            src={loginPreview}
            alt="开工吧产品预览"
            className="h-auto w-full max-w-[1200px] select-none object-contain"
            draggable={false}
          />
        </div>
      </main>
    </div>
  );
}

function stepDescription(screen: Screen, step: PhoneStep, phone: string) {
  if (step === 'phone') return screen === 'reset-password' ? '通过绑定手机号验证身份' : '使用已绑定手机号安全登录';
  if (step === 'code') return `验证码已发送至 +86 ${phone.slice(0, 3)} **** ${phone.slice(-4)}`;
  return screen === 'reset-password' ? '手机号验证成功，请设置新密码' : '手机号验证成功，请输入密码';
}

function FormHeading({ title, description }: { title: string; description: string }) {
  return (
    <div className="mb-[16px] text-center">
      <h2 className="text-[16px] font-medium text-[#18181a]">{title}</h2>
      <p className="mt-[4px] text-[12px] text-[#858b9c]">{description}</p>
    </div>
  );
}

function ClearButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" aria-label={label} onClick={onClick} className="grid size-[18px] shrink-0 place-items-center text-[#667085]">
      <IconFieldClear className="size-[18px]" />
    </button>
  );
}

function PasswordField({
  value,
  show,
  placeholder,
  onChange,
  onToggle,
  className = '',
  autoComplete = 'current-password',
  ariaLabel = '密码',
}: {
  value: string;
  show: boolean;
  placeholder: string;
  onChange: (value: string) => void;
  onToggle: () => void;
  className?: string;
  autoComplete?: string;
  ariaLabel?: string;
}) {
  return (
    <div className={`${className} flex h-[44px] w-full items-center gap-[8px] rounded-[10px] border border-[#e3e7f1] bg-white px-[16px] transition-colors focus-within:border-[#18181a]`}>
      <input
        value={value}
        type={show ? 'text' : 'password'}
        autoComplete={autoComplete}
        placeholder={placeholder}
        aria-label={ariaLabel}
        onChange={(event) => onChange(event.target.value)}
        className="min-w-0 flex-1 border-0 bg-transparent text-[14px] text-[#18181a] outline-none placeholder:text-[#757f9c]"
      />
      <button type="button" aria-label={show ? '隐藏密码' : '显示密码'} onClick={onToggle} className="grid size-[18px] shrink-0 place-items-center text-[#677185]">
        {show ? <IconFieldEyeOn className="size-[18px]" /> : <IconFieldEye className="size-[18px]" />}
      </button>
    </div>
  );
}

function ErrorMessage({ message }: { message: string }) {
  return <div role="alert" className="min-h-[28px] pt-[8px] text-center text-[12px] text-[#f04438]">{message}</div>;
}

function PrimaryButton({ loading, text, loadingText }: { loading: boolean; text: string; loadingText: string }) {
  return (
    <button
      type="submit"
      disabled={loading}
      className="mt-[4px] flex h-[40px] w-full items-center justify-center rounded-[10px] bg-[#18181a] text-[14px] text-white transition-colors hover:bg-[#18181a]/90 disabled:cursor-not-allowed disabled:opacity-60"
    >
      {loading ? loadingText : text}
    </button>
  );
}

function TextButton({ children, onClick }: { children: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="mt-[10px] self-center text-[12px] text-[#667085] transition-colors hover:text-[#1a71ff]">
      {children}
    </button>
  );
}
