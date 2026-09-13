// 출처: 전시관 AI 안내 서비스 (2026.04) — 프론트 고정 문구는 i18next. 한국어만 번들에 넣고 나머지 언어 사전은 선택 시점에 동적 import
// 콘텐츠(작품 설명 등)는 서버 사전 번역분을 API 로 받고, 버튼 · 안내문 같은 고정 문구만 이 사전이 담당한다.

import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import ko from './locales/ko.json';

const savedLang = localStorage.getItem('i18nextLng') || 'ko';

i18n.use(initReactI18next).init({
  resources: { ko: { translation: ko } },
  lng: savedLang,
  fallbackLng: 'ko',
  interpolation: { escapeValue: false },
});

// ko 를 뺀 나머지 사전은 코드 분할 — 키오스크 첫 화면 번들을 가볍게 유지
const localeModules = import.meta.glob(['./locales/*.json', '!./locales/ko.json']);

// 리소스 번들 로드 후 언어 변경 — changeLanguage 보다 먼저 로드해야 렌더링 시 키를 찾을 수 있음
export const changeLanguage = async (lang: string) => {
  localStorage.setItem('i18nextLng', lang);
  if (lang !== 'ko' && !i18n.hasResourceBundle(lang, 'translation')) {
    try {
      const loader = localeModules[`./locales/${lang}.json`];
      if (loader) {
        const module = (await loader()) as { default: Record<string, unknown> };
        i18n.addResourceBundle(lang, 'translation', module.default);
      }
    } catch {
      // 번역 파일 없으면 ko fallback
    }
  }
  return i18n.changeLanguage(lang);
};

// 새로고침 후 저장된 언어 번들 복원 — 렌더링 전 완료 보장 (main.tsx 가 await 한다)
export const i18nReady: Promise<void> =
  savedLang !== 'ko' ? changeLanguage(savedLang).then(() => {}) : Promise.resolve();

export default i18n;
