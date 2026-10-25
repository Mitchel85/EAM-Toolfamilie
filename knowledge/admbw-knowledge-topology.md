# ADMBw-Topologie-Regeln (MDG-Metaconstraints)

> Quelle: `NAFv4-ADMBw-MDG-2026.05.xml` — automatisch erzeugt (ohne Zeitstempel)
> 203 Stereotype mit Beziehungsregeln (Metaconstraints) · 133 vollständig (Quelle und Ziel) · 70 reine Rollenzeilen

## Lesart

- **Quelle:** client, source, end[0].role oder informationSource — je nach UML-Metaklasse.
- **Ziel:** supplier, target, end[1].role oder informationTarget — je nach UML-Metaklasse.
- **Weitere Rollen:** zusätzliche Metamodell-Beschränkungen (Rollennamen direkt aus der MDG).
- **Vollständigkeit:** Nur Regeln mit Quelle **und** Ziel (133 von 203) sind maschinell prüfbar; Regeln mit ausschließlich „Weiteren Rollen“ dienen als Referenz.
- **Abstrakte Typen:** Endpunkte, die auf abstrakte Stereotype verweisen (🔒), gelten für alle konkreten Subtypen. Die Auflösung steht unten unter „Abstrakte Endpunkte“.

| Stereotype | Erlaubte Quellen (client/source/end[0]) | Erlaubte Ziele (supplier/target/end[1]) | Weitere Rollen |
|---|---|---|---|
| AchievedEffect | Achiever | ActualState |  |
| ActivityPerformableUnderCondition | BusinessProcess | ActualCondition |  |
| ActivitySupportsService | OperationalActivity | ServiceSpecification |  |
| ActsUpon | OperationalActivity, OperationalActivityAction | OperationalExchangeItem, PaperForm |  |
| ActualCondition |  |  | classifier → Condition |
| ActualConditionToActualResource | ActualResource | ActualCondition |  |
| ActualEnduringTask |  |  | classifier → EnduringTask |
| ActualEnterprisePhase |  |  | classifier → EnterprisePhase |
| ActualEnvironment |  |  | classifier → Environment |
| ActualLocation |  |  | classifier → Location |
| ActualMeasurement |  |  | definingFeature → Measurement, owningInstance → ActualPropertySet |
| ActualMeasurementSetAppliesFor | ActualMeasurementSet | MeasurableElement |  |
| ActualOrganization |  |  | classifier → Organization |
| ActualOrganizationRole |  |  | definingFeature → PostRole, SubOrganization, owningInstance → ActualOrganization |
| ActualPerson |  |  | classifier → Person |
| ActualPost |  |  | classifier → Post |
| ActualProject |  |  | classifier → Project, definingFeature → ProjectRole |
| ActualProjectConsults | ActualProject | Organization |  |
| ActualProjectDependency | ActualProject | ActualProject |  |
| ActualProjectInforms | ActualProject | Organization |  |
| ActualProjectMilestone |  |  | classifier → ProjectMilestone |
| ActualProjectMilestoneRole |  |  | definingFeature → ProjectMilestoneRole, owningInstance → ActualProject, value.instance → ActualProjectMilestone |
| ActualPropertySet |  |  | classifier → PropertySet |
| ActualResource |  |  | classifier → ResourcePerformer |
| ActualResourceNeededByActualProjectMilestone | ActualResource | ActualProjectMilestone |  |
| ActualResourceRelationship | ActualResource | ActualResource | realizes → ResourceExchange |
| ActualResourceRole |  |  | definingFeature → ResourceRole, owningInstance → ActualResource |
| ActualResourceToActualProjectMilestone | ActualResource | ActualProjectMilestone |  |
| ActualService |  |  | classifier → ServiceSpecification |
| ActualServiceSpecificationRole |  |  | definingFeature → ServiceSpecificationRole, owningInstance → ActualService |
| AffectedActivity | OperationalExchangeItem | OperationalActivity |  |
| AffectedFunctions | ResourceExchangeItem | Function |  |
| AffectedResource | OperationalActivity | OperationalExchangeItem |  |
| AlignsWithGoal | OperationalActivity, OperationalAgent, ResourcePerformer, ServiceSpecification | EnterpriseGoal |  |
| ArbitraryConnector | ConceptRole | ConceptRole |  |
| ArchitecturalReference | ArchitecturalDescription | ArchitecturalDescription |  |
| ArchitecturalSequence | ArchitecturalDescription | ArchitecturalDescription |  |
| ArchitectureForProject | ActualProject, ActualProjectMilestone | ArchitecturalDescription |  |
| ArchitectureMetadata |  |  | annotatedElement → ArchitecturalDescription |
| BoundaryCondition | ResourceConnector | Environment |  |
| CapabilityDependency | Capability | Capability |  |
| CapabilityForTask | Capability | ActualEnduringTask, EnduringTask |  |
| CapabilityGeneralization | Capability | Capability |  |
| CapabilityRole |  |  | class → Capability, type → Capability |
| CapabilityRoleDependency | CapabilityRole | CapabilityRole |  |
| Checks | FitCriterion | BWRequirement |  |
| Classified | ArchitecturalDescription, DataElement, DocumentReference, InformationElement, ServiceSpecification | Classification |  |
| Command | OrganizationalResource, ResourceRole | OrganizationalResource, ResourceRole | conveyed → DataElement |
| CompetenceForRole | ResourceRole | Competence |  |
| CompliesViewpoint | View | Viewpoint |  |
| ConceptRole |  |  | class → HighLevelOperationalConcept, type → ConceptItem |
| ConcernForActualEnterprisePhase | ActualEnterprisePhase | Concern |  |
| ConcernForView | View | Concern |  |
| ConcernForViewpoint | Viewpoint | Concern |  |
| ConflictsWith | BWRequirement | BWRequirement |  |
| ConformsTo | UAFElement | Standard |  |
| ConsumedBy | ServiceSpecification, ServiceSpecificationRole | OperationalPerformer, OperationalRole |  |
| Consumes | OperationalActivity, OperationalActivityAction | ActualService, ServiceSpecification |  |
| Control | PhysicalResource, ResourceRole | PhysicalResource, ResourceRole | conveyed → DataElement |
| DataElement |  |  | owner → DataModel |
| DataElementStoredIn | DataElement | ResourcePerformer, ResourceRole |  |
| DataRole |  |  | class → ResourceAsset, type → DataElement |
| DerivedFrom | BWRequirement | UAFElement |  |
| DescribedBy | Architecture | ArchitecturalDescription |  |
| DesiredEffect | Desirer | ActualState |  |
| EnvironmentalCondition | Exhibits | Environment |  |
| EnvironmentalContext | Measurement | ActualCondition |  |
| EnvironmentProperty |  |  | class → Environment, type → Condition |
| Evaluates | FulfilmentCriterion | FitCriterion |  |
| Exhibits | CapableElement | Capability |  |
| Expresses | Architecture | ArchitecturalDescription |  |
| FieldedCapability |  |  | classifier → CapabilityConfiguration |
| FillsPost | ActualPerson | ActualPost |  |
| Forecast | SubjectOfForecast | SubjectOfForecast |  |
| ForecastPeriod | Forecast | ActualEnterprisePhase |  |
| FormStoredIn | PaperForm | Software |  |
| FunctionAction |  |  | activity → Function, behavior → Function |
| FunctionControlFlow | ActivityInitial, DecisionNode, ForkNode, FunctionAction, JoinNode, MergeNode | ActivityFinal, DecisionNode, FlowFinal, ForkNode, FunctionAction, JoinNode, MergeNode |  |
| FunctionEdge |  |  | owner → Function |
| FunctionObjectFlow | ActivityInitial, DecisionNode, ForkNode, FunctionAction, JoinNode, MergeNode | ActivityFinal, DecisionNode, FlowFinal, ForkNode, FunctionAction, JoinNode, MergeNode |  |
| FunctionSubject | Function | ResourceExchangeItem |  |
| GoalForActualEnterprisePhase | ActualEnterprisePhase | EnterpriseGoal |  |
| HostedOn | ResourceArchitecture, ResourceArtifact, ResourceRole | ResourceArchitecture, ResourceArtifact, ResourceRole |  |
| Implements | DataElement, Function, InformationElement, OperationalActivity, OperationalActivityAction, OperationalConstraint, ResourceConnector, ResourceConstraint, ResourceExchange, ResourceInterface, ResourcePerformer, ResourceRole, ServicePolicy, StrategicConstraint | ActualEnduringTask, InformationElement, OperationalActivity, OperationalActivityAction, OperationalAgent, OperationalConnector, OperationalConstraint, OperationalExchange, OperationalInterface, OperationalRole, ResourceConnector, ResourceConstraint, ServiceFunction, ServiceInterface, ServicePolicy, StrategicConstraint |  |
| ImplementsProtocol | ProtocolImplementation | Protocol |  |
| Information |  |  | annotatedElement → UAFElement |
| InformationElement |  |  | owner → DataModel |
| InformationRole |  |  | class → OperationalAsset, type → InformationElement |
| IsAccountableFor | Organization | ActualProject, ResourcePerformer, ServiceSpecification |  |
| IsCapableToPerform | OperationalAgent, ResourcePerformer, ServiceSpecification | BPMN2.0::Lane, BPMN2.0::Pool, Function, FunctionAction, OperationalActivity, OperationalActivityAction, ServiceFunction, ServiceFunctionAction |  |
| IsDuplicateOf | BWRequirement | BWRequirement |  |
| IsEquivalentToStandardElement | UAFElement | UAFElement |  |
| IsResponsibleFor | Organization | ActualProject, ResourcePerformer, ServiceSpecification |  |
| JustifiedBy | OperationalConstraint, ResourceConstraint, ServicePolicy, StrategicConstraint | Reference |  |
| LocationType | LocationHolder | Location |  |
| MapsToCapability | BusinessProcess | Capability |  |
| Measurement |  |  | class → PropertySet, type → MeasurementType |
| Metadata |  |  | annotatedElement → UAFElement |
| MilestoneDependency | ActualProjectMilestone | ActualProjectMilestone |  |
| NeedsModificationOf | ActualProject | PhysicalResource, ResourceArchitecture, ResourceRole |  |
| NeedsResource | ActualProject | PhysicalResource, ResourceArchitecture, ResourceRole |  |
| NeedsService | ActualProject | ServiceSpecification, ServiceSpecificationRole |  |
| OperationalActivity |  |  | ownedParameter → OperationalParameter |
| OperationalActivityAction |  |  | activity → OperationalActivity, behavior → OperationalActivity |
| OperationalActivityEdge |  |  | owner → OperationalActivity |
| OperationalAgent |  |  | ownedOperation → OperationalMethod, ownedPort → OperationalPort |
| OperationalArchitectureOfEnterprisePhase | ActualEnterprisePhase | OperationalArchitecture |  |
| OperationalConnector | OperationalPort, OperationalRole | OperationalPort, OperationalRole |  |
| OperationalControlFlow | BPMN2.0::Gateway, BPMN2.0::IntermediateEvent, BPMN2.0::StartEvent, OperationalActivityAction | BPMN2.0::EndEvent, BPMN2.0::Gateway, BPMN2.0::IntermediateEvent, OperationalActivityAction |  |
| OperationalExchange | OperationalActivity, OperationalAgent, OperationalRole, ServiceSpecification | OperationalActivity, OperationalAgent, OperationalRole, ServiceSpecification | conveyed → OperationalExchangeItem, realizingActivityEdge → OperationalActivityEdge, realizingConnector → OperationalConnector, realizingMessage → OperationalMessage |
| OperationalMessage |  |  | receiveEvent.event.operation → OperationalMethod |
| OperationalMessageFlow | BPMN2.0::IntermediateEvent, BPMN2.0::Lane, BPMN2.0::Pool, OperationalActivityAction | BPMN2.0::IntermediateEvent, BPMN2.0::Lane, BPMN2.0::Pool, OperationalActivityAction |  |
| OperationalMethod |  |  | method → OperationalActivity, ownedOperation → OperationalInterface, ownedParameter → OperationalParameter |
| OperationalObjectFlow | BPMN2.0::Gateway, BPMN2.0::IntermediateEvent, BPMN2.0::StartEvent, OperationalActivityAction | BPMN2.0::EndEvent, BPMN2.0::Gateway, BPMN2.0::IntermediateEvent, OperationalActivityAction |  |
| OperationalParameter |  |  | type → OperationalExchangeItem |
| OperationalPort |  |  | class → OperationalAgent, type → OperationalInterface |
| OperationalRole |  |  | class → OperationalAgent, OperationalArchitecture, OperationalPerformer, type → KnownResource, OperationalAgent, OperationalArchitecture, OperationalPerformer |
| OperationalSignalProperty |  |  | class → OperationalSignal, type → OperationalExchangeItem |
| OperationalStateDescription |  |  | owner → OperationalAgent |
| OriginatesFrom | UAFElement | Reference |  |
| OwnedMilestone | ActualProject | ActualProjectMilestone |  |
| OwnsActualMeasurementSet | MeasurableElement | ActualMeasurementSet |  |
| OwnsMeasurement | MeasurableElement | Measurement, MeasurementType |  |
| OwnsProcess | ActualOrganizationalResource | OperationalActivity |  |
| PartOfCatalogue | RequirementCategory | RequirementCatalogue |  |
| PartOfCategory | BWRequirement, RequirementCategory | RequirementCategory |  |
| PerformsInContext | OperationalRole, ResourceRole, ServiceSpecificationRole | BPMN2.0::Lane, BPMN2.0::Pool, Function, FunctionAction, OperationalActivity, OperationalActivityAction, ServiceFunction, ServiceFunctionAction |  |
| PhysicalArchitectureOfEnterprisePhase | ActualEnterprisePhase | ResourceArchitecture |  |
| PhysicalLocation | LocationHolder | ActualLocation |  |
| PostRole |  |  | class → Organization, Post, type → Post |
| ProblemDomain |  |  | class → OperationalArchitecture, type → OperationalPerformer |
| ProcessGeneralization | BusinessProcess | BusinessProcess |  |
| ProjectMilestoneRole |  |  | class → Project, type → ProjectMilestone |
| ProjectMilestoneToProjectTheme | ProjectMilestone | ProjectTheme |  |
| ProjectProvidesFunction | ActualProject | Function |  |
| ProjectRole |  |  | class → Project, type → Project |
| ProjectSequence | ActualProject | ActualProject |  |
| ProjectStatus |  |  | definingFeature → ProjectTheme |
| ProjectSupportActivity | ActualProject | OperationalActivity |  |
| PropertySetGeneralization | CapabilityConfiguration, PropertySet, System | CapabilityConfiguration, PropertySet, System |  |
| ProtocolLayer |  |  | class → Protocolstack, type → Protocol |
| Provides | OperationalPerformer, OperationalRole | ServiceSpecification, ServiceSpecificationRole |  |
| ProvidesCompetence | ActualOrganizationalResource | Competence |  |
| ProvidesServiceFunction | ServiceInterface | ServiceFunction |  |
| RatifiedStandards | ActualOrganization | Standard |  |
| RealiseRequirement | DataElement, Function, Measurement, MeasurementType, Protocol, Protocolstack, ResourcePerformer, ResourcePort, ResourceRole, ServiceFunction, ServiceInterface, ServiceSpecification, ServiceSpecificationRole, Standard | BWRequirement |  |
| RealizedDesiredEffect | AchievedEffect | DesiredEffect |  |
| RealizesRecommendation | UAFElement | Recommendation |  |
| RealizingAchievedEffect | DesiredEffect | AchievedEffect |  |
| RefersTo | Recommendation | Finding |  |
| Refines | BWRequirement | BWRequirement |  |
| Replaces | BWRequirement | BWRequirement |  |
| ReplaceStandardElement | Reference, UAFElement | Reference, UAFElement |  |
| RequiredEnvironment | LocationHolder | ActualEnvironment |  |
| RequiredResource | ProjectMilestone | ResourcePerformer |  |
| Requires | BWRequirement | BWRequirement |  |
| RequiresCompetence | OrganizationalResource | Competence |  |
| ResourceConnector | ResourcePort, ResourceRole | ResourcePort, ResourceRole |  |
| ResourceDependency | ResourcePerformer, ResourcePort, ResourceRole | ResourcePerformer, ResourcePort, ResourceRole |  |
| ResourceExchange | ResourcePerformer, ResourceRole, ServiceSpecificationRole | ResourcePerformer, ResourceRole, ServiceSpecificationRole | conveyed → ResourceExchangeItem, realizingActivityEdge → FunctionEdge, realizingConnector → ResourceConnector, realizingMessage → ResourceMessage |
| ResourceMessage |  |  | Connector → ResourceConnector, receiveEvent.event.operation → ResourceMethod |
| ResourceMethod |  |  | method → Function, ownedOperation → ResourceInterface, ResourcePerformer, ownedParameter → ResourceParameter |
| ResourceParameter |  |  | ownedParameter → Function, type → ResourceExchangeItem |
| ResourcePerformer |  |  | ownedPort → ResourcePort |
| ResourcePort |  |  | class → ResourcePerformer, type → ResourceInterface |
| ResourceRole |  |  | class → ResourcePerformer, type → ResourcePerformer |
| ResourceSignalProperty |  |  | class → ResourceSignal, type → ResourceExchangeItem |
| ResourceStateDescription |  |  | owner → ResourcePerformer |
| ResourceToServiceDependency | ResourcePerformer, ResourceRole | ServiceSpecification, ServiceSpecificationRole |  |
| Responsible | ActualProject | PhysicalResource, ResourceArchitecture, ResourceRole, ServiceSpecification |  |
| ResultsFrom | Finding | BPMN2.0::EndEvent, BPMN2.0::Gateway, BPMN2.0::IntermediateEvent, BPMN2.0::Lane, BPMN2.0::Pool, BPMN2.0::StartEvent, Classification, FitCriterion, FulfilmentCriterion, FunctionalRequirement, Measurement, MeasurementType, NonfunctionalRequirement, Reference, RequirementCatalogue, RequirementCategory, UAFElement |  |
| SameAs | Software, UAFElement | Software, UAFElement |  |
| Satisfy | Capability, OperationalActivityAction, ServiceSpecification, SubjectOfOperationalConstraint, SubjectOfResourceConstraint | OperationalConstraint, ResourceConstraint, ServicePolicy, StrategicConstraint |  |
| SecurityConstraint |  |  | constrainedElement → SubjectOfSecurityConstraint |
| ServiceConnector | ServicePort, ServiceSpecificationRole | ServicePort, ServiceSpecificationRole |  |
| ServiceDependency | ServiceSpecification | OperationalAgent, ResourcePerformer, ServiceSpecification |  |
| ServiceExchange | ServiceSpecification | ServiceSpecification | realizingConnector → ServiceConnector, realizingMessage → ServiceMessage |
| ServiceFunction |  |  | ownedParameter → ServiceParameter |
| ServiceFunctionAction |  |  | activity → ServiceFunction, behavior → ServiceFunction |
| ServiceGeneralization | ServiceSpecification | ServiceSpecification |  |
| ServiceInterface |  |  | ownedOperation → ServiceMethod |
| ServiceMethod |  |  | method → ServiceFunction, ownedParameter → ServiceParameter, receiveEvent.event.operation → ServiceMessage |
| ServiceParameter |  |  | type → OperationalExchangeItem |
| ServicePort |  |  | class → ServiceSpecification, type → ServiceInterface |
| ServiceProvision | ActualResource, ResourcePerformer, ResourceRole | ActualService, ServiceSpecification, ServiceSpecificationRole |  |
| ServiceSpecification |  |  | ownedOperation → ServiceMethod, ownedPort → ServicePort |
| ServiceSpecificationRole |  |  | class → ServiceSpecification, type → ServiceSpecification |
| ServiceStateDescription |  |  | owner → ServiceSpecification |
| StakeholderConcern | Stakeholder | Concern |  |
| StatementTask | ActualEnterprisePhase | ActualEnduringTask |  |
| StemsFrom | BWRequirement | BWRequirement |  |
| SubOrganization |  |  | class → Organization, type → Organization |
| SuccessorOf | ResourcePerformer, ServiceSpecification, Standard | ResourcePerformer, ServiceSpecification, Standard |  |
| TemporalPart |  |  | class → EnterprisePhase, type → EnterprisePhase |
| ToBeRealizedBy | BWRequirement | DataElement, Function, Measurement, MeasurementType, Protocol, Protocolstack, ResourcePerformer, ResourcePort, ResourceRole, ServiceFunction, ServiceInterface, ServiceSpecification, ServiceSpecificationRole, Standard |  |
| VersionOfConfiguration |  |  | class → WholeLifeConfiguration, type → VersionedElement |
| VersionReleased | ActualProjectMilestone | VersionedElement |  |
| VersionSuccession | VersionOfConfiguration | VersionOfConfiguration |  |
| VersionWithdrawn | ActualProjectMilestone | VersionedElement |  |
| ViewpointsInArchitecturalDescription | ArchitecturalDescription | Viewpoint |  |
| ViewpointToStakeholder | Viewpoint | Stakeholder |  |
| ViewsInArchitecturalDescription | ArchitecturalDescription | View |  |
| VisionForActualEnterprisePhase | ActualEnterprisePhase | EnterpriseVision |  |

## Abstrakte Endpunkte

Diese Typen dürfen **nicht instanziiert** werden. Für die Prüfung eines konkreten Modells sind sie auf die aufgeführten konkreten Subtypen aufzulösen.

| Abstrakter Typ | Konkrete Subtypen |
|---|---|
| 🔒 Achiever | ActualEnterprisePhase, ActualProject, ActualResource, ActualOrganization, ActualPerson, ActualPost, FieldedCapability, Function, SecurityProcess, OperationalActivity, StandardOperationalActivity, ServiceFunction, ServiceSpecification, StandardOperationalActivity |
| 🔒 ActualOrganizationalResource | ActualProject, ActualOrganization, ActualPerson, ActualPost |
| 🔒 ActualResponsibleResource | ActualOrganization, ActualPerson, ActualPost |
| 🔒 ActualState | ActualMeasurement, ActualProjectMilestoneRole, ActualPropertySet, ActualCondition, ActualEnvironment, ActualLocation, ActualEnduringTask, ActualEnterprisePhase, ActualMeasurementSet, ActualService, ProvidedServiceLevel, RequiredServiceLevel, ActualProjectMilestone, ActualResource, ActualProject, ActualOrganization, ActualPerson, ActualPost, FieldedCapability, ProjectStatus |
| 🔒 Architecture | OperationalArchitecture, ResourceArchitecture, CapabilityConfiguration, ResourceMitigation, SecurityEnclave, System |
| 🔒 Asset | InformationElement, OperationalArchitecture, OperationalPerformer, KnownResource, DataElement, Energy, NaturalResource, Organization, Person, Post, Project, Responsibility, ResourceArtifact, Software, Technology, ResourceArchitecture, CapabilityConfiguration, ResourceMitigation, SecurityEnclave, System |
| 🔒 AssetRole | DataRole, InformationRole, OperationalRole, ProblemDomain, ResourceRole, PostRole, ProjectRole, SubOrganization |
| 🔒 BusinessProcess | Function, SecurityProcess, OperationalActivity, StandardOperationalActivity, ServiceFunction |
| 🔒 BWRequirement | FunctionalRequirement, NonfunctionalRequirement |
| 🔒 CapableElement | ActualEnduringTask, ActualEnterprisePhase, ActualResource, ActualProject, ActualOrganization, ActualPerson, ActualPost, FieldedCapability, ActualService, ProvidedServiceLevel, RequiredServiceLevel, OperationalArchitecture, OperationalPerformer, KnownResource, Energy, NaturalResource, Organization, Person, Post, Project, Responsibility, ResourceArtifact, Software, Technology, ResourceArchitecture, CapabilityConfiguration, ResourceMitigation, SecurityEnclave, System, ServiceSpecification |
| 🔒 ConceptItem | InformationElement, OperationalArchitecture, OperationalPerformer, KnownResource, DataElement, Energy, NaturalResource, Organization, Person, Post, Project, Responsibility, ResourceArtifact, Software, Technology, ResourceArchitecture, CapabilityConfiguration, ResourceMitigation, SecurityEnclave, System, Location |
| 🔒 Desirer | Capability, CapabilityRole, OperationalArchitecture, OperationalPerformer, KnownResource, Energy, NaturalResource, Organization, Person, Post, Project, Responsibility, ResourceArtifact, Software, Technology, ResourceArchitecture, CapabilityConfiguration, ResourceMitigation, SecurityEnclave, System |
| 🔒 Exchange | OperationalExchange, ResourceExchange, Command, Control, ServiceExchange |
| 🔒 ExchangeItem | GeoPoliticalExtentType, InformationElement, InformationRole, OperationalSignal, KnownResource, Energy, NaturalResource, Organization, Person, Post, Project, Responsibility, ResourceArtifact, Software, Technology, ResourceArchitecture, CapabilityConfiguration, ResourceMitigation, SecurityEnclave, System, DataElement, DataRole, ResourceSignal |
| 🔒 FunctionEdge | FunctionControlFlow, FunctionObjectFlow |
| 🔒 InteractionMessage | OperationalMessage, ResourceMessage, ServiceMessage |
| 🔒 InteractionRole | OperationalRole, ProblemDomain, ResourceRole, PostRole, ProjectRole, SubOrganization, ServiceSpecificationRole |
| 🔒 LocationHolder | InformationElement, OperationalArchitecture, OperationalPerformer, KnownResource, DataElement, Energy, NaturalResource, Organization, Person, Post, Project, Responsibility, ResourceArtifact, Software, Technology, ResourceArchitecture, CapabilityConfiguration, ResourceMitigation, SecurityEnclave, System, OperationalRole, ProblemDomain, ResourceRole, PostRole, ProjectRole, SubOrganization |
| 🔒 MeasurableElement | AchievedEffect, ActivityPerformableUnderCondition, Alias, ArbitraryConnector, ArchitecturalDescription, ArchitecturalReference, ArchitecturalSequence, DataRole, InformationRole, OperationalRole, ProblemDomain, ResourceRole, PostRole, ProjectRole, SubOrganization, Function, SecurityProcess, OperationalActivity, StandardOperationalActivity, ServiceFunction, CapabilityDependency, CapabilityForTask, CapabilityRoleDependency, ConceptRole, Consumes, Definition, DesiredEffect, EnvironmentProperty, OperationalExchange, ResourceExchange, Command, Control, ServiceExchange, Exhibits, FillsPost, Forecast, Implements, Information, OperationalMessage, ResourceMessage, ServiceMessage, IsCapableToPerform, MapsToCapability, Measurement, Metadata, ArchitectureMetadata, MilestoneDependency, OperationalActivityAction, OperationalConnector, OperationalPort, OperationalRole, OperationalSignalProperty, OperationalStateDescription, OwnsProcess, PerformsInContext, FunctionControlFlow, FunctionObjectFlow, OperationalControlFlow, OperationalObjectFlow, ProcessGeneralization, OperationalMethod, ResourceMethod, ServiceMethod, OperationalParameter, ResourceParameter, ServiceParameter, FunctionAction, ServiceFunctionAction, ProjectMilestoneRole, ProjectSequence, ProjectTheme, InformationElement, OperationalArchitecture, OperationalPerformer, KnownResource, DataElement, Energy, NaturalResource, Organization, Person, Post, Project, Responsibility, ResourceArtifact, Software, Technology, ResourceArchitecture, CapabilityConfiguration, ResourceMitigation, SecurityEnclave, System, Capability, CapabilityRole, Competence, Concern, Condition, Environment, GeoPoliticalExtentType, Location, EnduringTask, EnterpriseGoal, EnterprisePhase, WholeLifeEnterprise, EnterpriseVision, HighLevelOperationalConcept, OperationalInterface, ProjectMilestone, OperationalSignal, ResourceSignal, ResourceInterface, ServiceInterface, ServiceSpecification, Standard, Protocol, Protocolstack, TemporalPart, View, Viewpoint, WholeLifeConfiguration, PropertySetGeneralization, CapabilityGeneralization, ServiceGeneralization, ProtocolLayer, ProvidesCompetence, RequiresCompetence, ResourceConnector, ResourcePort, ResourceSignalProperty, ResourceStateDescription, OperationalConstraint, ResourceConstraint, SecurityConstraint, ServicePolicy, StrategicConstraint, SameAs, ServiceConnector, ServiceMethod, ServicePort, ServiceProvision, ServiceSpecificationRole, ServiceStateDescription, TemporalPart, VersionOfConfiguration, VersionSuccession |
| 🔒 OperationalActivityEdge | OperationalControlFlow, OperationalObjectFlow |
| 🔒 OperationalAgent | OperationalArchitecture, OperationalPerformer, KnownResource |
| 🔒 OperationalAsset | InformationElement, OperationalArchitecture, OperationalPerformer, KnownResource |
| 🔒 OperationalExchangeItem | GeoPoliticalExtentType, InformationElement, InformationRole, OperationalSignal, KnownResource, Energy, NaturalResource, Organization, Person, Post, Project, Responsibility, ResourceArtifact, Software, Technology, ResourceArchitecture, CapabilityConfiguration, ResourceMitigation, SecurityEnclave, System |
| 🔒 OrganizationalResource | Organization, Person, Post, Project, Responsibility |
| 🔒 PhysicalResource | Energy, NaturalResource, Organization, Person, Post, Project, Responsibility, ResourceArtifact, Software, Technology |
| 🔒 ProcessEdge | FunctionControlFlow, FunctionObjectFlow, OperationalControlFlow, OperationalObjectFlow |
| 🔒 ProcessMessageFlow | OperationalMessageFlow |
| 🔒 ProcessOperation | OperationalMethod, ResourceMethod, ServiceMethod |
| 🔒 ProcessParameter | OperationalParameter, ResourceParameter, ServiceParameter |
| 🔒 ProcessUsage | FunctionAction, OperationalActivityAction, ServiceFunctionAction |
| 🔒 PropertySet | InformationElement, OperationalArchitecture, OperationalPerformer, KnownResource, DataElement, Energy, NaturalResource, Organization, Person, Post, Project, Responsibility, ResourceArtifact, Software, Technology, ResourceArchitecture, CapabilityConfiguration, ResourceMitigation, SecurityEnclave, System, Capability, CapabilityRole, Competence, Concern, Condition, Environment, GeoPoliticalExtentType, Location, EnduringTask, EnterpriseGoal, EnterprisePhase, WholeLifeEnterprise, EnterpriseVision, HighLevelOperationalConcept, OperationalInterface, ProjectMilestone, InformationRole, OperationalSignal, DataRole, ResourceSignal, ResourceInterface, ServiceInterface, ServiceSpecification, Standard, Protocol, Protocolstack, TemporalPart, View, Viewpoint, WholeLifeConfiguration, WholeLifeEnterprise |
| 🔒 ProtocolImplementation | ResourceConnector, ResourcePort |
| 🔒 Resource | GeoPoliticalExtentType, InformationElement, InformationRole, OperationalSignal, KnownResource, Energy, NaturalResource, Organization, Person, Post, Project, Responsibility, ResourceArtifact, Software, Technology, ResourceArchitecture, CapabilityConfiguration, ResourceMitigation, SecurityEnclave, System, DataElement, DataRole, ResourceSignal |
| 🔒 ResourceAsset | DataElement, KnownResource, Energy, NaturalResource, Organization, Person, Post, Project, Responsibility, ResourceArtifact, Software, Technology, ResourceArchitecture, CapabilityConfiguration, ResourceMitigation, SecurityEnclave, System |
| 🔒 ResourceExchangeItem | DataElement, DataRole, GeoPoliticalExtentType, KnownResource, Energy, NaturalResource, Organization, Person, Post, Project, Responsibility, ResourceArtifact, Software, Technology, ResourceArchitecture, CapabilityConfiguration, ResourceMitigation, SecurityEnclave, System, ResourceSignal |
| 🔒 ResourcePerformer | KnownResource, Energy, NaturalResource, Organization, Person, Post, Project, Responsibility, ResourceArtifact, Software, Technology, ResourceArchitecture, CapabilityConfiguration, ResourceMitigation, SecurityEnclave, System |
| 🔒 Rule | OperationalConstraint, ResourceConstraint, SecurityConstraint, ServicePolicy, StrategicConstraint |
| 🔒 Stakeholder | ActualProject, ActualOrganization, ActualPerson, ActualPost, Organization, Person, Post, Project, Responsibility |
| 🔒 SubjectOfForecast | InformationElement, OperationalArchitecture, OperationalPerformer, KnownResource, DataElement, Energy, NaturalResource, Organization, Person, Post, Project, Responsibility, ResourceArtifact, Software, Technology, ResourceArchitecture, CapabilityConfiguration, ResourceMitigation, SecurityEnclave, System, Competence, Standard, Protocol, Protocolstack |
| 🔒 SubjectOfOperationalConstraint | DataRole, InformationRole, OperationalRole, ProblemDomain, ResourceRole, PostRole, ProjectRole, SubOrganization, DataModel, InformationElement, OperationalActivity, SecurityProcess, StandardOperationalActivity, OperationalArchitecture, OperationalPerformer, KnownResource, OperationalExchange, OperationalSignal |
| 🔒 SubjectOfResourceConstraint | ActualResource, ActualProject, ActualOrganization, ActualPerson, ActualPost, FieldedCapability, DataElement, DataModel, Function, SecurityProcess, KnownResource, Energy, NaturalResource, Organization, Person, Post, Project, Responsibility, ResourceArtifact, Software, Technology, ResourceArchitecture, CapabilityConfiguration, ResourceMitigation, SecurityEnclave, System, ResourcePort, ResourceRole, PostRole, ProjectRole, SubOrganization |
| 🔒 SubjectOfSecurityConstraint | InformationElement, OperationalArchitecture, OperationalPerformer, KnownResource, DataElement, Energy, NaturalResource, Organization, Person, Post, Project, Responsibility, ResourceArtifact, Software, Technology, ResourceArchitecture, CapabilityConfiguration, ResourceMitigation, SecurityEnclave, System, DataRole, InformationRole, OperationalRole, ProblemDomain, ResourceRole, PostRole, ProjectRole, SubOrganization, OperationalExchange, ResourceExchange, Command, Control, ServiceExchange, SecurityProcess |
| 🔒 UAFElement | ActualEnterprisePhase, ActualProject, ActualResource, ActualOrganization, ActualPerson, ActualPost, FieldedCapability, Function, SecurityProcess, OperationalActivity, StandardOperationalActivity, ServiceFunction, ServiceSpecification, ActualEnterprisePhase, ActualResourceRelationship, ActualResourceRole, ActualOrganizationRole, ActualMeasurement, ActualProjectMilestoneRole, ActualPropertySet, ActualCondition, ActualEnvironment, ActualLocation, ActualEnduringTask, ActualMeasurementSet, ActualService, ProvidedServiceLevel, RequiredServiceLevel, ActualProjectMilestone, ProjectStatus, OperationalArchitecture, ResourceArchitecture, CapabilityConfiguration, ResourceMitigation, SecurityEnclave, System, OperationalPerformer, KnownResource, Energy, NaturalResource, Organization, Person, Post, Project, Responsibility, ResourceArtifact, Software, Technology, InformationElement, DataElement, Location, Capability, CapabilityRole, OperationalRole, ProblemDomain, ResourceRole, PostRole, ProjectRole, SubOrganization, AchievedEffect, ActivityPerformableUnderCondition, Alias, ArbitraryConnector, ArchitecturalDescription, ArchitecturalReference, ArchitecturalSequence, DataRole, InformationRole, CapabilityDependency, CapabilityForTask, CapabilityRoleDependency, ConceptRole, Consumes, Definition, DesiredEffect, EnvironmentProperty, OperationalExchange, ResourceExchange, Command, Control, ServiceExchange, Exhibits, FillsPost, Forecast, Implements, Information, OperationalMessage, ResourceMessage, ServiceMessage, IsCapableToPerform, MapsToCapability, Measurement, Metadata, ArchitectureMetadata, MilestoneDependency, OperationalActivityAction, OperationalConnector, OperationalPort, OperationalSignalProperty, OperationalStateDescription, OwnsProcess, PerformsInContext, FunctionControlFlow, FunctionObjectFlow, OperationalControlFlow, OperationalObjectFlow, ProcessGeneralization, OperationalMethod, ResourceMethod, ServiceMethod, OperationalParameter, ResourceParameter, ServiceParameter, FunctionAction, ServiceFunctionAction, ProjectMilestoneRole, ProjectSequence, ProjectTheme, Competence, Concern, Condition, Environment, GeoPoliticalExtentType, EnduringTask, EnterpriseGoal, EnterprisePhase, WholeLifeEnterprise, EnterpriseVision, HighLevelOperationalConcept, OperationalInterface, ProjectMilestone, OperationalSignal, ResourceSignal, ResourceInterface, ServiceInterface, Standard, Protocol, Protocolstack, TemporalPart, View, Viewpoint, WholeLifeConfiguration, PropertySetGeneralization, CapabilityGeneralization, ServiceGeneralization, ProtocolLayer, ProvidesCompetence, RequiresCompetence, ResourceConnector, ResourcePort, ResourceSignalProperty, ResourceStateDescription, OperationalConstraint, ResourceConstraint, SecurityConstraint, ServicePolicy, StrategicConstraint, SameAs, ServiceConnector, ServicePort, ServiceProvision, ServiceSpecificationRole, ServiceStateDescription, VersionOfConfiguration, VersionSuccession, DataModel |
| 🔒 VersionedElement | KnownResource, Energy, NaturalResource, Organization, Person, Post, Project, Responsibility, ResourceArtifact, Software, Technology, ResourceArchitecture, CapabilityConfiguration, ResourceMitigation, SecurityEnclave, System, ServiceSpecification |
