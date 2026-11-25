# Política de referências canônicas SPDX

## Decisão e escopo

O EduDownloader adota `ADOPT_CANONICAL_REFERENCE_POLICY_FOR_P3_REVIEW` como
política técnica. Ela permite preservar textos oficiais da SPDX License List
como referências de identidade para expressões já comprovadas por metadata
upstream exata. Não é uma decisão jurídica e não autoriza publicação.

Esta política separa obrigatoriamente:

- `SOURCE_CORRESPONDENCE`;
- `LICENSE_IDENTITY`;
- `UPSTREAM_LICENSE_TEXT`;
- `CANONICAL_REFERENCE_TEXT`;
- `ATTRIBUTION_METADATA`;
- `NOTICE_IDENTITY`;
- `NOTICE_DELIVERY`;
- `LEGAL_REVIEW`.

`SPDX_CANONICAL_REFERENCE_TEXT` nunca significa `UPSTREAM_LICENSE_TEXT`. A
ausência de arquivo integral no upstream permanece registrada como `ABSENT` ou
`PARTIAL`, mesmo quando a referência canônica está disponível.

## Snapshot e provenance

As referências estão fixadas na SPDX License List 3.28.0, repositório oficial
`spdx/license-list-data`, tag anotada `v3.28.0`, objeto de tag
`779ef2e5dff6d4af389c53de5e97116ab0bb52e8` e commit de conteúdo
`c4a7237ec8f4654e867546f9f409749300f1bf4c`.

O manifesto `SPDX_CANONICAL_REFERENCES.json` registra caminho oficial, URL no
commit exato, tamanho e SHA-256 de cada texto. O namespace
`docs/compliance/licenses/spdx-reference/` é deliberadamente separado das
evidências de licença originalmente publicadas pelos componentes.

Foram preservadas somente as quatro referências necessárias nesta fase:
`MIT`, `Apache-2.0`, `CC0-1.0` e `Zlib`.

## Invariantes fail-closed

1. Identidade e versão do componente continuam ancoradas na evidência upstream.
2. A expressão SPDX é preservada literalmente; nenhuma expressão é inferida.
3. Referência SPDX nunca promove upstream text para `PRESENT`.
4. Expressão com `OR` exige referências para todas as alternativas.
5. Expressão futura com `WITH` exige referência da licença e da exceção.
6. Snapshot, commit, paths, tamanhos e hashes devem estar pinados.
7. A provenance deve declarar `SPDX_CANONICAL_REFERENCE_TEXT`.
8. Ausência de upstream text não reabre source correspondence.
9. Attribution específica não é preenchida a partir do texto SPDX.
10. `LEGAL_REVIEW` permanece `P3_REQUIRED`; `LEGAL_APPROVED` é proibido.

## Aplicação à D11H

Os dez componentes da categoria C conservam identidade resolvida pela metadata
upstream, upstream text `ABSENT`, referência canônica `AVAILABLE` e revisão
`P3_REQUIRED`.

Os cinco componentes da categoria D conservam suas expressões completas:
`MIT OR Apache-2.0` ou `MIT OR Apache-2.0 OR Zlib`. O conjunto canônico contém
todas as alternativas, sem escolha unilateral. Para `zune-core` e `zune-jpeg`,
o `LICENSE-ZLIB` integral e a informação Apache parcial continuam como
evidência upstream original; as referências SPDX são somente complementares.

## Fronteiras preservadas

- `SOURCE_CORRESPONDENCE = TECHNICALLY_COMPLETE` não significa compliance
  jurídica completa.
- `NOTICE_IDENTITY = RESOLVED` não significa entrega.
- `NOTICE_DELIVERY = PENDING_FIX` até um novo candidato controlado carregar os
  notices.
- `LEGAL_REVIEW = P3_REQUIRED`.
- `BUILD_REPRODUCIBILITY = P2_SEPARATE_PENDING`.
- O candidato congelado histórico não recebe estes textos e permanece intacto.
