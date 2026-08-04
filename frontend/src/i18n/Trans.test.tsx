import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Trans } from './Trans';
import { TermsConsent } from '../components/auth/TermsConsent';
import { useLocaleStore, DEFAULT_LOCALE } from '../store/useLocaleStore';
import type { TranslationKey } from '.';

beforeEach(() => {
  useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
});

describe('Trans', () => {
  it('substitutes a React node for a placeholder', () => {
    render(
      <Trans
        k="auth.closedAlpha"
        nodes={{ supportEmail: <a href="mailto:x@y.z">x@y.z</a> }}
      />,
    );
    expect(screen.getByRole('link', { name: 'x@y.z' })).toBeInTheDocument();
    expect(document.body).toHaveTextContent('This is a closed alpha.');
  });

  it('leaves a placeholder with no node as visible text', () => {
    render(<Trans k="auth.closedAlpha" nodes={{}} />);
    expect(document.body).toHaveTextContent('{supportEmail}');
  });

  it('never treats the translation string as HTML', () => {
    // A dictionary entry is data. If it could inject markup, translating a
    // string would become a way to add elements to the page.
    render(
      <Trans
        k={'probe' as TranslationKey}
        nodes={{}}
        vars={{}}
      />,
    );
    // Unknown key falls through to the key itself; nothing is parsed.
    expect(document.body.querySelector('script')).toBeNull();
  });

  it('does not pull placeholder nodes off Object.prototype', () => {
    render(<Trans k="auth.closedAlpha" nodes={Object.create({ supportEmail: 'inherited' }) as Record<string, never>} />);
    expect(document.body).toHaveTextContent('{supportEmail}');
    expect(document.body).not.toHaveTextContent('inherited');
  });
});

describe('TermsConsent in Czech', () => {
  // The end-to-end proof that one-key-with-holes works: the same component,
  // the same two links, a sentence whose parts are inflected to fit it.
  beforeEach(() => {
    useLocaleStore.setState({ locale: 'cs', explicit: true });
  });

  it('renders the Czech sentence with both links in place', () => {
    render(<TermsConsent checked={false} onChange={vi.fn()} />);
    expect(document.body).toHaveTextContent(
      'Souhlasím s Podmínkami služby a Zásadami ochrany osobních údajů.',
    );
  });

  it('keeps the hrefs, which are language-independent', () => {
    render(<TermsConsent checked={false} onChange={vi.fn()} />);
    expect(screen.getByRole('link', { name: 'Podmínkami služby' })).toHaveAttribute(
      'href',
      '/terms',
    );
    expect(
      screen.getByRole('link', { name: 'Zásadami ochrany osobních údajů' }),
    ).toHaveAttribute('href', '/privacy');
  });

  it('still labels the checkbox, so the whole sentence toggles it', () => {
    // Translating must not break the label association — the sentence is the
    // click target, and it is now assembled from fragments.
    render(<TermsConsent checked={false} onChange={vi.fn()} id="cs-terms" />);
    const box = screen.getByRole('checkbox');
    expect(box).toHaveAttribute('id', 'cs-terms');
    expect(box.closest('label')).toHaveAttribute('for', 'cs-terms');
  });
});
