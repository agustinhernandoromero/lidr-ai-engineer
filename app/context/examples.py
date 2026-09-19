"""Static historical estimation examples used for Context-Augmented Generation (CAG)."""

from typing import Any, Dict, List

ESTIMATION_EXAMPLES: List[Dict[str, Any]] = [
    {
        "meeting_summary": (
            "El cliente necesita una plataforma web de gestión de inventario para pequeñas y medianas "
            "empresas. Requiere autenticación de usuarios con roles (admin, operador, auditor), un CRUD "
            "completo de productos y categorías con carga masiva vía CSV, un dashboard analítico con "
            "gráficos de stock bajo y rotación de inventario, y un sistema de alertas por email. "
            "El cliente no tiene diseño previo pero sí wireframes básicos."
        ),
        "estimation": """## Estimación: Plataforma Web de Gestión de Inventario

### 1. Resumen Ejecutivo
Desarrollo de una solución web integral para la gestión y control de inventario con roles diferenciados, dashboard visual y alertas automatizadas.

### 2. Desglose de Tareas y Estimación de Horas:
1. **Diseño UI/UX y Prototipado**:
   - Sistema de diseño y componentes UI: 20 horas
   - Prototipado navegable en Figma (Dashboard, CRUDs, Alertas): 20 horas
   - *Subtotal: 40 horas*

2. **Arquitectura y Backend API**:
   - Modelado de base de datos relacional (PostgreSQL) y migraciones: 15 horas
   - Autenticación segura (OAuth2 / JWT) y control de acceso basado en roles (RBAC): 20 horas
   - Endpoints CRUD para productos, stock y categorías: 30 horas
   - Procesamiento asíncrono para importación/exportación CSV: 15 horas
   - Servicio de notificaciones y alertas por correo: 10 horas
   - *Subtotal: 90 horas*

3. **Frontend Web (SPA / Dashboard)**:
   - Integración de vistas y layout responsive: 25 horas
   - Módulo de gestión y tablas interactivas con filtros avanzados: 25 horas
   - Dashboard analítico con gráficos interactivos (ApexCharts/Recharts): 20 horas
   - *Subtotal: 70 horas*

4. **Testing, QA y DevOps**:
   - Pruebas unitarias e integración (Backend + Frontend): 25 horas
   - Configuración de pipeline CI/CD y despliegue en entorno Cloud: 15 horas
   - *Subtotal: 40 horas*

---
### 3. Totales y Equipo
- **Total estimado**: **240 horas**
- **Equipo recomendado**: 1 Tech Lead / Full-stack Senior (part-time), 1 Desarrollador Frontend, 1 Desarrollador Backend, 1 Diseñador UX/UI (fase inicial).
- **Duración estimada**: **7 - 9 semanas**
- **Riesgos identificados**: Rendimiento en cargas masivas de CSV de más de 50.000 filas; mitigado con tareas asíncronas vía workers.
""",
    },
    {
        "meeting_summary": (
            "Startup de salud digital requiere una aplicación móvil (iOS y Android) para seguimiento de "
            "hábitos de bienestar y reserva de citas con especialistas. Requiere pasarela de pago (Stripe), "
            "notificaciones push recordatorias, chat en tiempo real entre paciente y doctor, y sincronización "
            "con Apple Health / Google Fit. Ya disponen del diseño en Figma completamente finalizado."
        ),
        "estimation": """## Estimación: App Móvil de Salud Digital y Telemedicina

### 1. Resumen Ejecutivo
Aplicación móvil multiplataforma (Flutter / React Native) conectada a backend escalable con videoconsulta/chat en tiempo real y pagos integrados.

### 2. Desglose de Tareas y Estimación de Horas:
1. **Backend y Servicios Cloud**:
   - Arquitectura serverless / contenedores y base de datos: 25 horas
   - Autenticación con verificación en 2 pasos (SMS/Email): 15 horas
   - Motor de reservas y disponibilidad horaria de especialistas: 30 horas
   - Integración con pasarela de pagos (Stripe Connect): 25 horas
   - Infraestructura de chat y mensajería en tiempo real (WebSockets / Firebase): 30 horas
   - *Subtotal: 125 horas*

2. **Desarrollo Mobile App (Multiplataforma)**:
   - Maquetación fiel desde Figma y estados de interfaz: 45 horas
   - Flujo de reserva de citas y checkout: 25 horas
   - Módulo de chat en vivo con soporte de imágenes/documentos: 30 horas
   - Integración SDK HealthKit (Apple) y Google Health Connect: 25 horas
   - Configuración de Notificaciones Push personalizadas: 15 horas
   - *Subtotal: 140 horas*

3. **Aseguramiento de Calidad y Despliegue en Stores**:
   - Pruebas E2E en dispositivos reales (iOS y Android): 30 horas
   - Auditoría de seguridad y cumplimiento básico HIPAA/GDPR: 20 horas
   - Publicación en Apple App Store y Google Play Store: 15 horas
   - *Subtotal: 65 horas*

---
### 3. Totales y Equipo
- **Total estimado**: **330 horas**
- **Equipo recomendado**: 2 Desarrolladores Mobile Senior, 1 Desarrollador Backend Cloud, 1 Especialista QA / Seguridad.
- **Duración estimada**: **10 - 12 semanas**
- **Riesgos identificados**: Políticas estrictas de aprobación en App Store para apps de telemedicina; mitigado preparando consentimientos informados desde el inicio.
""",
    },
    {
        "meeting_summary": (
            "Empresa de consultoría busca automatizar la generación de reportes mensuales. Necesitan "
            "un servicio que se conecte a tres APIs externas (Google Analytics, CRM Salesforce y base de datos SQL), "
            "procese los datos, genere un informe en formato PDF y PowerPoint, y lo envíe por correo "
            "a una lista de distribución cada primer día de mes."
        ),
        "estimation": """## Estimación: Servicio Automatizado de Generación de Reportes

### 1. Resumen Ejecutivo
Desarrollo de un microservicio de extracción de datos (ETL liviano), procesamiento y generación de documentos PDF/PPTX automáticos.

### 2. Desglose de Tareas y Estimación de Horas:
1. **Conectores y Extracción de Datos**:
   - Conector con API de Google Analytics v4: 12 horas
   - Conector con Salesforce REST API: 15 horas
   - Conector y queries optimizadas a BD SQL interna: 10 horas
   - *Subtotal: 37 horas*

2. **Motor de Procesamiento y Generación de Documentos**:
   - Pipeline de consolidación y limpieza de métricas: 15 horas
   - Motor de renderizado de plantillas PDF con gráficos vectoriales: 25 horas
   - Generador automatizado de presentaciones PowerPoint (.pptx): 20 horas
   - *Subtotal: 60 horas*

3. **Programación, Notificaciones y Despliegue**:
   - Scheduler de tareas periódicas (Cron / Celery / Cloud Scheduler): 10 horas
   - Servicio de despacho de emails con adjuntos y logs de auditoría: 10 horas
   - Configuración de alertas de fallo y monitoreo: 8 horas
   - Testing unitario e integración con mocks: 15 horas
   - *Subtotal: 43 horas*

---
### 3. Totales y Equipo
- **Total estimado**: **140 horas**
- **Equipo recomendado**: 1 Desarrollador Backend Python Senior, 1 Data/Automation Engineer.
- **Duración estimada**: **4 - 5 semanas**
- **Riesgos identificados**: Límites de rate-limiting en API de Salesforce; mitigado con caching y paginación controlada.
""",
    },
]
