# ADMBw Knowledge: Konnektor-Regeln & Viewpoint-Übersicht

> Quelle: `NAFv4-ADMBw-MDG-2026.05.xml` — automatisch erzeugt (ohne Zeitstempel)

## Goldene Regel

Jede Beziehung besteht aus EA-Metatyp und Stereotyp. Der Stereotyp muss auf diesen Metatyp anwendbar sein; Element- und Konnektor-Ebene sind strikt getrennt.

## Element-Metatypen & ihre Stereotype

| EA-Metatyp | Anzahl | Stereotype |
|---|---:|---|
| **Class** (68) | 68 | `Architecture`, `Asset`, `Capability`, `CapabilityConfiguration`, `Classification`, `Competence`, `Concern`, `DataElement`, `DocumentReference`, `EnduringTask`, `Energy`, `EnterpriseGoal` +56 weitere |
| **Object** (21) | 21 | `Achiever`, `ActualCondition`, `ActualEnduringTask`, `ActualEnterprisePhase`, `ActualEnvironment`, `ActualLocation`, `ActualMeasurementSet`, `ActualOrganization`, `ActualOrganizationalResource`, `ActualPerson`, `ActualPost`, `ActualProject` +9 weitere |
| **Part** (20) | 20 | `AssetRole`, `CapabilityRole`, `ConceptRole`, `DataRole`, `InformationRole`, `Measurement`, `OperationalRole`, `OperationalSignalProperty`, `PostRole`, `ProblemDomain`, `ProjectMilestoneRole`, `ProjectRole` +8 weitere |
| **Activity** (6) | 6 | `BusinessProcess`, `Function`, `OperationalActivity`, `SecurityProcess`, `ServiceFunction`, `StandardOperationalActivity` |
| **Slot** (6) | 6 | `ActualMeasurement`, `ActualOrganizationRole`, `ActualProjectMilestoneRole`, `ActualResourceRole`, `ActualServiceSpecificationRole`, `ProjectStatus` |
| **Note** (5) | 5 | `Alias`, `ArchitectureMetadata`, `Definition`, `Information`, `Metadata` |
| **Action** (3) | 3 | `FunctionAction`, `OperationalActivityAction`, `ServiceFunctionAction` |
| **DataType** (3) | 3 | `Condition`, `GeoPoliticalExtentType`, `Location` |
| **Operation** (3) | 3 | `OperationalMethod`, `ResourceMethod`, `ServiceMethod` |
| **Package** (3) | 3 | `ArchitecturalDescription`, `DataModel`, `ElementCatalogue` |
| **Parameter** (3) | 3 | `OperationalParameter`, `ResourceParameter`, `ServiceParameter` |
| **Port** (3) | 3 | `OperationalPort`, `ResourcePort`, `ServicePort` |
| **Requirement** (3) | 3 | `BWRequirement`, `FunctionalRequirement`, `NonfunctionalRequirement` |
| **StateMachine** (3) | 3 | `ResourceStateDescription`, `ServiceStateDescription`, `StateDescription` |
| **Constraint** (2) | 2 | `Rule`, `SecurityConstraint` |
| **Signal** (2) | 2 | `OperationalSignal`, `ResourceSignal` |
| **Lifeline** (1) | 1 | `InteractionRole` |

## Konnektor-Metatypen & ihre Stereotype

| EA-Metatyp | Anzahl | Stereotype |
|---|---:|---|
| **Dependency** (100) | 100 | `AchievedEffect`, `ActivityPerformableUnderCondition`, `ActsUpon`, `ActualConditionToActualResource`, `ActualMeasurementSetAppliesFor`, `ActualProjectConsults`, `ActualProjectDependency`, `ActualProjectInforms`, `ActualResourceNeededByActualProjectMilestone`, `ActualResourceToActualProjectMilestone`, `AffectedActivity`, `AffectedFunctions` +88 weitere |
| **Abstraction** (10) | 10 | `CapabilityForTask`, `Consumes`, `Exhibits`, `Implements`, `IsCapableToPerform`, `MapsToCapability`, `OwnsProcess`, `PerformsInContext`, `RequiresCompetence`, `ServiceProvision` |
| **InformationFlow** (6) | 6 | `ActualResourceRelationship`, `Command`, `Control`, `OperationalExchange`, `ResourceExchange`, `ServiceExchange` |
| **Generalization** (4) | 4 | `CapabilityGeneralization`, `ProcessGeneralization`, `PropertySetGeneralization`, `ServiceGeneralization` |
| **Message** (4) | 4 | `InteractionMessage`, `OperationalMessage`, `ResourceMessage`, `ServiceMessage` |
| **Realisation** (4) | 4 | `ActivitySupportsService`, `Evaluates`, `RealiseRequirement`, `RealizesRecommendation` |
| **Connector** (3) | 3 | `OperationalConnector`, `ResourceConnector`, `ServiceConnector` |
| **ControlFlow** (3) | 3 | `FunctionControlFlow`, `OperationalControlFlow`, `OperationalMessageFlow` |
| **Aggregation** (2) | 2 | `PartOfCatalogue`, `PartOfCategory` |
| **ObjectFlow** (2) | 2 | `FunctionObjectFlow`, `OperationalObjectFlow` |

## Vollständige Viewpoint-Liste (52 Viewpoints, 6 Kategorien)

### Architecture Foundation Viewpoints

| Kürzel | Name | Beschreibung |
|---|---|---|
| A1 | Meta-Data Definitions | Architectures, particularly large ones, usually require meta-data tags to aid with searching and discovery |
| A2 | Architecture Products | The A2 Viewpoint specifies the structure of an architecture, and the products that describe the architecture |
| A3 | Architecture Correspondence | ISO/IEC/IEEE42010 introduces the idea of architecture correspondence and correspondence rules |
| A4 | Methodology Used | The A4 Viewpoint specifies the methodology used for the architecting activities |
| A5 | Architecture Status | Since NAFv3.0, it has been possible to assign version numbers to views and specify their approval dates |
| A6 | Architecture Version | Where the A5 Viewpoint shows the current version number and approval status for the architecture, the A6 Viewpoint shows the complete history of the architecture |
| A7 | Architecture Compliance | The A7 Viewpoint gives the overall specification of architecture meta-data |
| A8 | Standards | The A8 Viewpoint encompasses both technical and non-technical standards |
| Ar | Architecture Roadmap | The Ar Viewpoint shows the history of the architecture project as well as its future direction |

### Concept Viewpoints

| Kürzel | Name | Beschreibung |
|---|---|---|
| C1 | Capability Taxonomy | The C1 Viewpoint specifies all the capabilities that are referenced throughout one or more architectures – i.e |
| C2 | Enterprise Vision | The purpose of the C2 Viewpoint is to provide a strategic context for the capabilities described in the architecture and to specify the scope for the architecture |
| C3 | Capability Dependencies | The C3 Viewpoint is intended to provide a means of analysing the dependencies between capabilities and between capability clusters |
| C4 | Standard Processes | The C4 Viewpoint specifies Standard Operational Activities that can be re-used across multiple logical architectures (e.g |
| C5 | Effects | The purpose of the C5 Viewpoint is to describe the operational effect of the capabilities, activities and services according to the expected goals |
| C7 | Performance Parameters | In the C7 Viewpoint the capability requirements (and existing capabilities) can be expressed in terms of Measures of Effectiveness (MoEs) |
| C8 | Planning Assumptions | The C8 Viewpoint is concerned with identification and description of assumptions that have been made for the implementation of capabilities |
| Cr | Capability Roadmap | The Cr Viewpont supports the Capability Audit process by providing a method to identify gaps or duplications in capability provision |

### Logical Specification Viewpoints

| Kürzel | Name | Beschreibung |
|---|---|---|
| L1 | Node Types | The L1 Viewpoint defines all of the Nodes that will appear in a Logical Architecture |
| L2 | Logical Scenario | The L2 Viewpoint specifies Nodes (elements of capability) in context of each other |
| L2-L3 | Logical Concept | The L2-L3 Viewpoint is concerned with providing an executive level, scenario-based communication of the architecture purpose, scope and content |
| L3 | Node Interactions | L3 is used to provide further detail of the interoperability requirements associated with the operational capability of interest |
| L4 | Logical Activities | The L4 Viewpoint describes the operational activities that are being conducted within the mission or scenario |
| L5 | Logical States | The L5 Viewpoint specifies the typical states a node may have and the possible transitions between those states (i.e |
| L6 | Logical Sequence | Operational Event-Trace Descriptions, sometimes called sequence diagrams, event scenarios or timing diagrams, allow the tracing of interactions between nodes in a scenario or critical sequence of events |
| L7 | Information Model | The L7 Viewpoint is used to document the business information |
| L8 | Logical Constraints | The L8 Viewpoint is used to constrain the logical architecture without forcing a particular solution |
| Lr | Lines of Development | The Lr Viewpoint is primarily intended to support the acquisition process across multiple projects or programmes, highlighting dependencies the logical dependencies between capabilities, projects and the integration of all lines of development to achieve a successfully integrated military capability |

### Physical Resource Specification Viewpoints

| Kürzel | Name | Beschreibung |
|---|---|---|
| L4-P4 | Activity To Function Mapping | The L4-P4 Viewpoint depicts the mapping of Resource Functions (and optionally, the resources that provide them) to operational activities and/or service functions |
| P1 | Resource Types | The P1 Viewpoint collects together all the Resource Types in the architecture together with a depiction of their performance characteristics |
| P2 | Resource Structure | The P2 Viewpoint links together the operational and physical architecture viewpoints by depicting how types of Resource are structured and interact to realize the logical architecture specified in L2, Logical Scenario |
| P3 | Resource Connectivity | The networks and pathways documented in a P3 Viewpoint represent the physical implementation of the logical flows identified in a L2, Logical Scenario, or L3, Node Interactions View |
| P4 | Resource Functions | The Functionality Description provides detailed information regarding the allocation of functions to resources, and flows between Resource Functions |
| P5 | Resource States | The P5 Viewpoint identifies the states a Resource can be, the allowable changes between those states, and the stimuli (e.g |
| P6 | Resource Sequence | The P6 Viewpoint is valuable for moving to the next level of detail from the initial solution design, to help define a sequence of functions and Resource Interactions, and to ensure that each participating Resource or Port has the necessary information, at the right time, in order to perform its assigned functionality |
| P7 | Data Model | The P7 Viewpoint is one of the architectural products closest to actual system design in the NAF |
| P8 | Resource Constraints | The P8 Viewpoint describes constraints on the Resources, Resource Functions, data and communications that make up a Physical Architecture |
| Pr | Configuration Management | The Pr Viewpoint provides an overview of how Resource Assets change over time (note that NAF v3.1 only allowed for Capability Configurations whereas now this is opened up to all Resource Types) |

### Requirement Viewpoints

| Kürzel | Name | Beschreibung |
|---|---|---|
| R2 | Requirement Catalogue | The R2 represents a catalog of requirements in the architectural model |
| R3 | Requirement Dependencies | The R3 is used to show dependencies between different requirements |
| R7 | Requirement Derivation | The R7 assigns functional and non-functional requirements to the demanding architectural elements |
| R8 | Requirement Fulfilment | The R8 is used to determine and map acceptance and evaluation criteria for the individual functional and non-functional requirements |
| Rr | Requirement Realization | In the Rr, requirements are assigned to the realizing architectural elements |

### Service Specification Viewpoints

| Kürzel | Name | Beschreibung |
|---|---|---|
| C1-S1 | Capability to Service Mapping | A C1-S1 Viewpoint presents a simple mapping of services to capabilities, showing which services contribute to which capability |
| S1 | Service Taxonomy | The purpose of the S1 Viewpoint is to provide a governance structure for a Service-Oriented Architecture |
| S2 | Service Structure | The S2 Viewpoint is concerned with identification and description of how services are structured to create a higher-aggregated service |
| S3 | Service Interfaces | The S3 Viewpoint is concerned with the identification and definition of service interfaces |
| S4 | Service Functions | The S4 Viewpoint is the key behavioural specification for services |
| S5 | Service States | The S5 Viewpoint is a specification of the allowable states of a service, and the possible transitions between them |
| S6 | Service Interactions | Service Interaction Descriptions, sometimes called sequence diagrams, event scenarios or timing diagrams, allow the tracing of interactions between services in a composition or critical sequence of events |
| S7 | Service Interface Parameters | Specifies the interfaces that a service provides and uses, defines which services are compatible with which other services |
| S8 | Service Policy | The S8 Viewpoint specifies constraints against services to which implementations must conform |
| Sr | Service Roadmap | The Sr Viewpoint supports the Service Audit process by providing a method to identify gaps or duplications in service provision |

