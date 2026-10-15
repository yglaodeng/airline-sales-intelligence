# Episode 41 — Aviation Intelligence: How Every Function Connects

This is the English transcript for the full-system walkthrough. The narration follows one operating chain from data intake and route decisions through inventory, ticketing, after-sales service, cash, profit, and final acceptance.

> The system screens use desensitized demonstration records. External airline, GDS, OTA, payment, and ticketing integrations are described with their actual verification boundaries; the video does not claim that every production interface is live.

## Chapter 1 — Industry Pain Points and System Goals

Over the past forty episodes, we've taken this system apart, one real problem at a time. Today, I'd like to bring those pieces back together—and show you how they work as one journey.

Let me start with a question I hear all the time: is there still a future in airline ticket sales?

I believe there is. But it won't look like the business we used to know.

Simply selling whatever seats happen to be available is getting harder. The real opportunity now is planning: knowing which route is worth taking on, when to secure seats, and how to sell them without losing control of inventory or profit.

That's why I built this system. In this episode, I'd like to walk through it with you, step by step, and explain why every part is there.

We will follow one complete business journey—from the first data source and route decision, through procurement, daily planning, inventory, channels, pricing, orders, ticketing, after-sales service, cash, and profit. Along the way, I will show what each function is for, where its data comes from, how the system uses it, and how every result can be traced back when something goes wrong.

## Chapter 2 — The Cockpit and Data Intake

Now that the industry problem and the system goal are clear, we can follow the order in which the business actually happens. The first step is not to rush into a model or build a dashboard. It is to bring together the facts scattered across stores, ticketing, inventory, after-sales service, and finance. If the underlying data does not use the same definitions, every later judgment about routes, inventory, and profit can be wrong from the start.

The data may come from O.T.A. store orders, G.D.S. or supplier ticketing results, airline schedules and disruption notices, internal sales details, inventory ledgers, customer-service tickets, and payment or settlement records. Business users may also upload Excel or C.S.V. files. The system first standardizes the route, flight, departure date, amount, order number, and inventory batch. It then checks for missing fields, format errors, duplicate records, and failed links. Data that fails validation remains at the intake gate and cannot carry an error further downstream.

Only after intake is complete does the cockpit have a trustworthy base table. It brings opportunities, risks, pending work, and exceptions into one operating view, while allowing every indicator to trace back to its source record. At this point, we do not yet have a procurement decision. We have a factual base from which a decision can be made. The next step is to use those facts to answer the first operating question: which routes are worth pursuing?

## Chapter 3 — Route Sales Strategy and Procurement Decisions

With a unified data base, the system can make its first decision. Planned pre-purchase cannot begin by asking how many seats to buy. It must first confirm which routes have sustained demand, which departure dates concentrate that demand, what prices the market accepts, whether supply is stable, and how much cost the team can carry. Deciding whether a route is worth operating comes first, because experience alone can lead either to unsold inventory or missed opportunities.

This stage reuses the orders, issued tickets, cancellations, and refunds standardized in the previous chapter. It also adds price and supply information from G.D.S. sources, airlines, O.T.A. platforms, and suppliers, together with demand calendars for holidays, exhibitions, school terms, and other events. The system aligns them by route, departure date, and advance-sales day to produce demand curves, price bands, supply-stability indicators, and risk warnings.

This stage must deliver four explicit outcomes: whether to operate the route, when to secure seats, how many seats to secure, and the maximum acceptable procurement cost. The procurement direction becomes valid only after a person confirms all four. Once the route and total resource volume are fixed, the question changes from whether to operate to how this block of seats should be sold on every day before departure.

## Chapter 4 — Sales Models, Daily Plans, and Calibration

Once the route, procurement quantity, and cost are confirmed, the system must move beyond a total-volume decision. Thirty days, fifteen days, and three days before departure require very different pricing, sales-speed, and inventory-protection strategies. The sales model turns the procurement conclusion into daily targets, so the team knows how many seats to sell today, at what price, and how much inventory to protect.

The model takes the procurement quantity and cost, flight date, historical sales curve, current transaction price, market quotes, channel order progress, cancellations and refunds, and the target profit. For every departure date, the system creates a daily sales calendar with a volume target, reference price, protected inventory, and priority channels. Each target is assigned to a date and an owner.

Actual daily sales, transaction prices, and remaining inventory return to the same plan. The system compares plan with reality and determines whether the gap comes from changing demand, an excessive price, insufficient inventory allocation, or weak channel execution. The sales calendar is therefore not created once and forgotten; it is recalibrated with real outcomes. When a gap appears, the team still needs to know what action to take, which leads to deeper analysis and scenario comparison.

## Chapter 5 — Deep Analysis, Recommendations, and Price Backtesting

The daily plan shows where performance has moved away from target, but a gap does not automatically mean the price should be cut. Slow sales may come from the price, a channel that has not opened enough volume, incorrectly allocated inventory, or even a flight-time change that has weakened demand. Deep analysis takes the deviation from the previous stage, brings the related factors together, explains the cause first, and then proposes an action.

The system takes the demand window from route strategy, cost and remaining seats from procurement and inventory, sales progress from orders, and market prices from fare and comparison modules. It then applies minimum-profit, price-limit, sales-prohibition, and approval rules. Desensitized and structured data may enter intelligent analysis, but every recommendation must include its reasoning: why seats should be added, a price protected or reduced, a channel adjusted, or the sales pace changed, and how the action may affect volume, revenue, gross profit, and inventory clearance.

Recommendations enter a review area first. Historical backtesting or scenario comparison shows the possible outcome, and only after a business user confirms the choice does it become an executable task. The system has now converted a detected gap into a proposed action. The next question is whether real seat inventory exists to execute that action, so the business chain naturally moves into inventory preparation.

## Chapter 6 — Sales Inventory, Seat Blocks, and Group Inventory

The strategy may define how to sell, but it can only be executed when the inventory base is true. After procurement is confirmed, seats move from a contract or quotation into managed sales resources. The system must know the route, flight, date, and booking class for every inventory batch, together with how many seats are occupied, sold, allocated, and still available.

Initial inventory may come from an airline or supplier seat-block confirmation, a procurement contract, a P.N.R., or an allocation list. A procurement user may also enter it after confirmation. Orders and issued tickets create holds and deductions. Cancellations, refunds, exchanges, and procurement adjustments release or transfer seats. Group business also contributes group requests, confirmed passenger counts, and internal allocations. The system creates seat-block inventory by flight and procurement batch, while group inventory separately records applications, confirmations, allocations, and balances.

Every inventory change creates a ledger entry. The system uses those entries to calculate the true sellable quantity and raises warnings when too many seats remain close to departure, when seats are allocated twice, or when allocation approaches the limit. The seat resource is now ready, but the system still cannot accept an order until it knows where the inventory will be sold, who owns the order, and who will issue the ticket. The next stage is therefore stores, channels, and ticketing routes.

## Chapter 7 — Stores, Channels, Contacts, and Ticketing Routes

Inventory answers what can be sold. Stores and channels answer where it will be sold, who receives the order, and who issues the ticket. The same ticket may be sold through several O.T.A. stores, direct channels, or corporate customers, and it may be issued by different suppliers. If an order has only a number but no source, settlement relationship, or owner, ticketing, after-sales service, and reconciliation will all become mixed together.

Store and account data comes from platform onboarding records and internal account lists. Channel, supplier, settlement-policy, and service-hour data comes from cooperation agreements. Contacts come from customer, supplier, platform, and internal role directories. Ticketing routes combine the airline, route, booking class, price policy, cost, and handling priority. The system turns these records into stable mappings so an incoming order can immediately identify its source, responsibility relationship, and processing path.

Orders that meet automatic-ticketing conditions enter the corresponding queue. Orders requiring judgment enter a work list with complete supporting data. When an exception occurs, the service ticket can reach the responsible person directly. We now know who handles the order, but we must still determine which policy applies, what the true cost is, and what selling price should be used. Otherwise, the route may be correct while the quote is still wrong.

## Chapter 8 — Policies, Fares, Price Comparison, and Repricing

An order with a source and a handling path still cannot be completed immediately, because an airline price is not an isolated number. Taxes, incentives, booking class, applicable dates, sales restrictions, and exchange or refund rules all change the true cost. The policy and fare modules use the earlier route, inventory, and channel information to determine whether a quote is valid and whether the sale can preserve profit.

Policies may come from airline and supplier documents, email, back-office notices, or formal interfaces. Fares and taxes come from G.D.S. sources, airlines, suppliers, and O.T.A. searches. Market prices come from authorized comparison tasks. Internal procurement cost, target profit, minimum selling price, and sellable inventory define the operating boundary. The system converts written policies into computable conditions and converts quotes from different sources into complete costs that can be compared.

During quoting, ordering, and ticketing, the system checks whether the policy applies. When market prices change, it combines inventory progress with the profit floor to generate a repricing recommendation, while preserving the supporting evidence and approval result. The customer, processor, and price are now determined. The strategy must next enter a real order and complete ticketing and ticket verification.

## Chapter 9 — Strategy Tasks, Orders, Ticketing, and Verification

Route decisions, sales plans, inventory, channels, and prices must eventually become business execution. A recommendation without an owner, deadline, and returned result remains only a recommendation. An order that cannot show whether it is waiting for payment, ticketing, or verification cannot support a customer commitment. Strategy tasks and the order center turn earlier decisions into traceable actions.

Strategy tasks come from route, model, repricing, and inventory modules. Orders come from O.T.A. stores, direct channels, corporate customers, or manual entry. Passenger and itinerary information comes from booking data. Payment status comes from payment or settlement systems. P.N.R.s, ticket numbers, and issuance results come from G.D.S. sources, airlines, suppliers, or ticketing staff. The system assigns a unique identifier to every task and order and records its evidence, owner, deadline, and every status change.

The order enters the queue selected by the ticketing route. After issuance, the P.N.R. and ticket number are written back, and the verification module checks the order, passenger, flight, and ticket against one another. Missing data, channel failure, processing timeout, or a ticket mismatch immediately moves the case into exception handling. This completes the path from plan to ticketing, but the chain is not over because a delivered ticket may still face a schedule change, exchange, cancellation, or refund.

## Chapter 10 — Disruptions, After-Sales Service, Cash, and Profit

An issued ticket completes the first delivery, but it does not establish the final business result. A schedule change may require notification, rebooking, or refund. A cancellation changes the ticket, inventory, revenue, and cost at the same time. The after-sales module carries the original order and ticket number forward so every later change remains attached to the same business transaction.

Disruption information comes from airlines, G.D.S. sources, supplier notices, or manual confirmation. Exchange and refund requests come from customers, stores, and service teams. Applicable rules come from the original fare policy and supplier conditions. Refunds, fees, receivables, and cash received come from payment platforms, settlement statements, bank transactions, and finance updates. The original order provides the passenger, flight, ticket number, selling price, and procurement cost, allowing the system to decide whom to notify, which solution to execute, how much to refund, and who owns the work.

The system links every disruption and after-sales ticket back to the original order and continuously records notifications, proposed solutions, owners, refund progress, and final outcomes. The finance module then aggregates sales, procurement cost, taxes, fees, refunds, receivables, and cash received. It distinguishes estimated, confirmed, and paid states and calculates the real profit for the order and route. The after-sales state has returned to the order, but one question remains: after a cancellation or refund, was the corresponding inventory released as well?

## Chapter 11 — Order and Inventory Synchronization

The previous chapter changed order and ticket states. This chapter ensures that the change does not stop on the order page. If an order occupies a seat but inventory is not reduced, the system may oversell. If a cancelled order does not release inventory, a sellable seat becomes unavailable. Order and inventory synchronization must therefore answer exactly which order changed which inventory batch, and at what time.

The link uses the order number, inventory batch, flight date, booking class, passenger count, order status, ticketing status, and cancellation, refund, exchange, and external callback events. These inputs come from the order center, ticketing result, after-sales ticket, channel interface, and inventory ledger. The system performs a hold, deduction, release, or transfer according to the business state, and uses an event identifier to recognize duplicate callbacks so the same action cannot run twice.

Every change produces an inventory ledger entry. Front-end sellable quantity is aggregated from that ledger, and an operator can trace the specific order, time, and action. A single order now forms a closed loop across ordering, ticketing, after-sales service, inventory, and finance. The next step moves beyond one transaction and aggregates all business for the day to determine whether overall operations have deviated from plan.

## Chapter 12 — Operating Statistics and Nightly Review

After a single order closes its loop, management must return to the full operating picture. At the end of a day, the number of tickets sold is not enough. The team must know whether sales were timely, inventory is healthy, refunds are increasing, cash has arrived, and profit has met the target. Operating statistics take the results of the earlier modules and answer two questions: where did we deviate today, and what should we change first tomorrow?

The system aggregates route strategy, sales plans, channel orders, ticketing time, inventory ledgers, after-sales refunds, cash, and profit. Planned targets come from the sales model. Actual outcomes come from order, ticketing, and finance records. Exception causes come from tasks, work tickets, and the operating process. Because the same flight, inventory batch, order, and ticket identifiers were used throughout, an aggregate can still drill down to its source record instead of ending at a single number.

The nightly review compares plan and reality by route, store, channel, date, and owner. It identifies demand, price, channel, inventory, and execution problems, then generates tomorrow's tasks for adding supply, repricing, clearing inventory, chasing ticket issuance, and collecting receivables. Operating results now feed back into the next day's plan. But as more users view, change, and export data, the system must also control who may perform each action and whether every action remains traceable.

## Chapter 13 — Export, Cleanup, Permissions, and Audit Logs

Once the business chain is running, risk comes not only from business decisions but also from system use. Who can view, edit, approve, or export? Can data be recovered after an operational mistake? These questions directly affect every earlier feature. Permissions, export, cleanup, and logs are therefore not secondary pages; they form the governance layer that keeps the system operating over time.

Employee, role, organization, and account-validity data determine the access scope. Strategy, inventory, order, ticket, after-sales, and finance data determine the objects that can be acted upon. Login, query, modification, approval, execution, export, and cleanup actions create audit records. The system restricts view, edit, approval, and execution permissions by role. An export keeps its filter conditions and generation record. A cleanup displays the affected scope and requires the corresponding authorization before it can continue.

Critical operations record the account, time, object, state before and after the change, and final result. This supports collaboration and handover while also allowing the team to identify responsibility and recover data when an exception occurs. Only after internal data, process, and permission boundaries are clear is the system ready to exchange real outcomes with airlines, G.D.S. providers, suppliers, O.T.A. platforms, and payment services. That is the role of the external interface layer.

## Chapter 14 — External Interfaces and Verified Business Responses

The earlier modules control how the system decides and acts internally, but the final result in aviation often occurs outside the system. A page that says ticket issued does not prove that the airline or supplier actually issued a ticket. A page that says refunded does not prove that cash has arrived. The external interface layer sends internal orders and tasks outward and brings formal results back into the system.

Integration materials come from the other party's official interface documentation, field dictionary, account authorization, key or certificate, test environment, and callback specification. Business data comes from search, ordering, ticketing, refund, payment, and notification interfaces. Runtime evidence includes request identifiers, response codes, callback content, failure reasons, and external-platform states. An adapter converts different external fields into one internal object and handles authentication, requests, callbacks, retries, monitoring, and transfer to a person when automation fails.

External order numbers, ticket numbers, prices, and payment results are written back to the original business record and continue to drive inventory, after-sales service, and finance. Without a formal response, the state may only remain processing or pending verification. Every feature now has its own input and output, but the outputs still have to be proven as one continuous transaction. The next stage uses one case to connect every feature.

## Chapter 15 — Connecting Every Feature Through One Case

If every page uses a different route, inventory batch, and order, each feature may appear to produce a result while the full system proves nothing about continuity. The purpose of an end-to-end case is to place the outputs of the first fourteen chapters into one business chain. The same route, flight, inventory batch, and order must keep the same business identifiers from beginning to end.

The case starts with historical sales, market prices, and procurement quotes to create a route decision and procurement plan. After procurement is confirmed, the system establishes inventory and a daily sales plan, then links stores, channels, policies, and fares. An incoming order creates a seat hold, ticket issuance, and verification. A schedule change or refund is then introduced so the team can observe the resulting changes in inventory, refunds, cash, and profit. The source material may come from historical spreadsheets, airlines and suppliers, sales platforms, ticketing systems, customer service, and finance, but once it enters the system it must be linked by flight, inventory batch, order, and ticket identifiers.

Finally, operating statistics aggregate the plan, execution, exceptions, and outcome for the same case. Audit logs prove who completed each action and when. We can now see whether the features truly connect. Yet running the chain once is still not enough for delivery. Final acceptance must test the normal path, exception paths, and state continuity after a restart.

## Chapter 16 — Final Acceptance and Delivery Boundaries

Once one case has connected all features, final acceptance no longer checks buttons page by page. It checks whether the whole business can move from input to result. The acceptance standard has three parts: the normal business path completes end to end, invalid data or external failures are stopped at the correct point, and data, tasks, and states remain consistent after the system restarts.

The normal path uses a desensitized but complete business sample covering route, procurement, inventory, order, ticket, after-sales service, and finance. Exception paths use a copy or test environment with missing fields, insufficient inventory, out-of-range prices, channel failures, invalid ticket numbers, and payments without a response. Before each step, the expected input, action, state, and result are written down. The team then verifies quantities, amounts, owners, and external responses.

The system meets the delivery condition only when the normal chain completes, the exception chain is stopped correctly, and every state remains traceable after restart. The functional order is now clear: standardize data, decide the route and procurement plan, create sales plans and recommendations, prepare inventory and channel policies, handle orders, ticketing, and after-sales service, synchronize inventory and finance, and finally close the loop through review, governance, external responses, and end-to-end acceptance.

## Conclusion

Looking back at this chain, the system does not place a dozen features side by side. It makes the result of one step become the input of the next. Route decisions drive procurement. Procurement creates inventory and sales plans. Channels and policies make that inventory sellable. Orders and tickets record real execution, and after-sales activity continues to change inventory, cash, and profit.

Those results return to the operating review and create the next day's tasks for adding supply, repricing, clearing inventory, chasing ticket issuance, and collecting receivables. Permissions and logs keep the whole process traceable. External interfaces bring formal results from airlines, suppliers, O.T.A. platforms, and payment services back into the system. Every feature now has a defined position, and we can explain why it must sit between the functions before and after it.

A valuable aviation intelligence system is not defined by the number of pages or figures. Every data item must have a source. Every state must have an owner. Every recommendation must become an actionable task. Every result must trace back to the original business record. From data intake to final acceptance, that is a complete operating loop that people can understand, execute, and verify.

## Closing Thanks

Thank you for following this series and for staying with me through these forty-one episodes. You are always welcome to reach out, share your thoughts, or leave a comment.
