# Feedback Log

Aquí se registra cada sesión de uso del MVP. Es el mecanismo principal por el que el proyecto evoluciona: lo que funciona se refuerza, lo que falla se corrige, los patrones nuevos se incorporan.

## Cuándo escribir una entrada

- Después de cada sesión de revisión del dashboard donde tomas (o decides no tomar) una decisión basada en lo que la herramienta te muestra.
- Cuando la herramienta da una señal y te resulta sorprendente, claramente errónea, o claramente acertada.
- Cuando ves en CT/charts/Twitter algo que la herramienta debería haber capturado y no lo hizo.
- Cuando un trade real (entrada o salida) se cierra con outcome conocido, para registrar si la señal predijo bien.

## Formato del archivo

Nombre: `YYYY-MM-DD-N.md` donde N es el número de sesión del día (1, 2, ...).

Estructura:

```markdown
---
date: YYYY-MM-DD
session: N
duration_min: 15
projects_reviewed: [HYPE, ZEC, PENGU, ...]
---

## Lo que la herramienta mostró
[Resumen de las señales relevantes para los proyectos revisados]

## Lo que decidí
[Acción tomada o no tomada, y por qué]

## Lo que la herramienta NO capturó
[Información de fuentes externas que debería estar en la herramienta]

## Aciertos / Errores
[Si hay outcomes conocidos de decisiones previas, registrar aquí]

## Cambios propuestos a la herramienta
- [ ] [Cambio 1, archetype/signal/threshold afectado]
- [ ] [Cambio 2]
```

## Ciclo de evolución

1. **Diario**: el usuario escribe entradas en `feedback/`.
2. **Semanal** (viernes): review conjunta. Se sintetizan los patrones recurrentes en `learnings/`.
3. **Cuando emerge un cambio estructural**: se crea un ADR nuevo en `decisions/` y se actualiza el código.
4. **Cuando un signal demuestra ser ruidoso o redundante 3+ veces**: se desactiva o reweighta. Se documenta el cambio en `learnings/signal-performance.md`.

## Anti-patterns

- ❌ Escribir solo cuando algo va mal. Los aciertos también enseñan (especialmente los que confirmaron una decisión no obvia).
- ❌ Registrar el qué sin el por qué. "Vendí HYPE" es inútil. "Vendí HYPE porque funding extremo + smart wallets distribuyendo desde hace 2 semanas" es procesable.
- ❌ Acumular ideas sin convertirlas en ADRs cuando son estructurales. El feedback debe materializar cambios.
